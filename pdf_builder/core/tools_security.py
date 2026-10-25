"""Sécurité : chiffrement, caviardage, assainissement, signatures numériques."""

from __future__ import annotations

import datetime as dt
import re
import tempfile
import warnings
from pathlib import Path

import pymupdf as fitz

from .registry import Param, ToolError, tool
from .utils import POSITION_CHOICES, anchor_point, parse_color, parse_pages, safe_filename

# ---------------------------------------------------------------------------
# Chiffrement
# ---------------------------------------------------------------------------


@tool(
    id="protect",
    name="Protéger par mot de passe",
    category="security",
    icon="🔐",
    description="Chiffre le PDF (AES-256) avec mot de passe d'ouverture et restrictions d'impression, copie, modification.",
    chainable=True,
    keywords="mot de passe chiffrer crypter protéger sécuriser aes permissions",
    params=[
        Param("user_pw", "Mot de passe d'ouverture", "password", "", help="Laisser vide pour n'appliquer que des restrictions"),
        Param("owner_pw", "Mot de passe propriétaire (restrictions)", "password", "", help="Vide = généré automatiquement"),
        Param("allow_print", "Autoriser l'impression", "bool", True),
        Param("allow_copy", "Autoriser la copie du texte", "bool", False),
        Param("allow_modify", "Autoriser la modification", "bool", False),
        Param("allow_annotate", "Autoriser les annotations et formulaires", "bool", True),
        Param("algo", "Chiffrement", "choice", "aes256", choices=[("aes256", "AES 256 bits (recommandé)"), ("aes128", "AES 128 bits (compatibilité)")]),
    ],
)
def protect(path: Path, p: dict, ctx) -> list[Path]:
    import secrets

    doc = ctx.open(path)
    user_pw = p.get("user_pw") or ""
    owner_pw = p.get("owner_pw") or secrets.token_urlsafe(18)
    if not user_pw and not p.get("owner_pw"):
        ctx.report("Aucun mot de passe d'ouverture : seules les restrictions sont appliquées.")
    perm = fitz.PDF_PERM_ACCESSIBILITY
    if p["allow_print"]:
        perm |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
    if p["allow_copy"]:
        perm |= fitz.PDF_PERM_COPY
    if p["allow_modify"]:
        perm |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE
    if p["allow_annotate"]:
        perm |= fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM
    algo = fitz.PDF_ENCRYPT_AES_256 if p["algo"] == "aes256" else fitz.PDF_ENCRYPT_AES_128
    dest = ctx.output(path, "_protégé")
    doc.save(str(dest), garbage=3, deflate=True, encryption=algo, owner_pw=owner_pw, user_pw=user_pw, permissions=perm)
    doc.close()
    return [dest]


@tool(
    id="unlock",
    name="Supprimer le mot de passe",
    category="security",
    icon="🔓",
    description="Retire le mot de passe et les restrictions d'un PDF dont vous connaissez le mot de passe.",
    chainable=True,
    keywords="déverrouiller enlever mot de passe décrypter unlock",
    params=[Param("password", "Mot de passe actuel", "password", "", help="Laisser vide si seules des restrictions sont présentes")],
)
def unlock(path: Path, p: dict, ctx) -> list[Path]:
    if p.get("password"):
        ctx.passwords[str(path)] = p["password"]
    doc = ctx.open(path)
    dest = ctx.output(path, "_déverrouillé")
    doc.save(str(dest), garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
    doc.close()
    return [dest]


# ---------------------------------------------------------------------------
# Caviardage
# ---------------------------------------------------------------------------
PRESETS = {
    "email": ("Adresses e-mail", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "phone": ("Numéros de téléphone", r"(?:\+\d{2,3}[ .-]?|\b0)[1-9](?:[ .-]?\d{2}){4}\b"),
    "iban": ("IBAN", r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"),
    "card": ("Cartes bancaires", r"\b(?:\d{4}[ -]?){3}\d{1,4}\b"),
    "nir": ("N° de sécurité sociale", r"\b[12] ?\d{2} ?(?:0[1-9]|1[0-2]|[2-9]\d) ?(?:\d{2}|2[AB]) ?\d{3} ?\d{3}(?: ?\d{2})?\b"),
    "date": ("Dates", r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})\b"),
    "url": ("Liens web", r"\bhttps?://[^\s]+|\bwww\.[^\s]+"),
    "amount": ("Montants (€, $)", r"(?:[€$£] ?\d[\d  .,]*\d|\d[\d  .,]*\d ?(?:€|EUR|\$|USD|£))"),
}


def find_sensitive(page: fitz.Page, terms: list[str], patterns: list[str], case: bool = False) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    text = page.get_text("text")
    matches: set[str] = set()
    for pat in patterns:
        flags = 0 if case else re.IGNORECASE
        for line in text.splitlines():
            for m in re.finditer(pat, line, flags):
                if m.group(0).strip():
                    matches.add(m.group(0).strip())
    for term in terms:
        if term.strip():
            matches.add(term.strip())
    for s in matches:
        for q in page.search_for(s, quads=False):
            rects.append(q)
    return rects


@tool(
    id="redact",
    name="Caviarder (RGPD)",
    category="security",
    icon="⬛",
    description="Efface définitivement des mots, expressions ou données personnelles détectées (e-mails, IBAN, téléphones…).",
    chainable=True,
    keywords="caviarder masquer anonymiser rgpd censurer supprimer données personnelles redact",
    params=[
        Param("terms", "Mots ou expressions à caviarder", "text", "", placeholder="Un terme par ligne"),
        Param("regex", "Expression régulière (avancé)", "str", ""),
        Param("p_email", "Adresses e-mail", "bool", False),
        Param("p_phone", "Numéros de téléphone", "bool", False),
        Param("p_iban", "IBAN", "bool", False),
        Param("p_card", "Cartes bancaires", "bool", False),
        Param("p_nir", "N° de sécurité sociale", "bool", False),
        Param("p_date", "Dates", "bool", False),
        Param("p_url", "Liens web", "bool", False),
        Param("p_amount", "Montants", "bool", False),
        Param("color", "Couleur du masque", "color", "#000000"),
        Param("label", "Texte sur le masque", "str", "", placeholder="ex. [SUPPRIMÉ]"),
        Param("mark_only", "Seulement marquer (vérifier avant d'appliquer dans l'éditeur)", "bool", False),
    ],
)
def redact(path: Path, p: dict, ctx) -> list[Path]:
    terms = [t for t in re.split(r"[\n]+", p.get("terms") or "") if t.strip()]
    patterns = [PRESETS[k][1] for k in PRESETS if p.get(f"p_{k}")]
    if p.get("regex"):
        try:
            re.compile(p["regex"])
        except re.error as exc:
            raise ToolError(f"Expression régulière invalide : {exc}") from exc
        patterns.append(p["regex"])
    if not terms and not patterns:
        raise ToolError("Indiquez au moins un terme à caviarder ou cochez une catégorie de données.")
    doc = ctx.open(path)
    fill = parse_color(p["color"])
    total = 0
    for page in doc:
        ctx.progress(page.number / doc.page_count, f"Page {page.number + 1}")
        rects = find_sensitive(page, terms, patterns)
        for r in rects:
            page.add_redact_annot(r, text=p.get("label") or None, fill=fill, text_color=(1, 1, 1))
        total += len(rects)
        if rects and not p["mark_only"]:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
    ctx.report(f"{path.name} : {total} zone(s) {'marquée(s)' if p['mark_only'] else 'caviardée(s)'}.")
    if not p["mark_only"]:
        doc.scrub(metadata=False, javascript=False, embedded_files=False, attached_files=False, clean_pages=True, hidden_text=False, redactions=False, remove_links=False, reset_fields=False, reset_responses=False, thumbnails=True, xml_metadata=False)
    dest = ctx.save(doc, ctx.output(path, "_caviardé"), garbage=4, clean=True)
    doc.close()
    return [dest]


@tool(
    id="sanitize",
    name="Assainir (confidentialité)",
    category="security",
    icon="🛡️",
    description="Supprime métadonnées, JavaScript, pièces jointes, texte caché et autres données invisibles avant diffusion.",
    chainable=True,
    keywords="métadonnées javascript nettoyer confidentialité vie privée anonymiser",
    params=[
        Param("metadata", "Métadonnées (auteur, logiciel…)", "bool", True),
        Param("javascript", "JavaScript", "bool", True),
        Param("attachments", "Pièces jointes", "bool", True),
        Param("hidden_text", "Texte caché", "bool", True),
        Param("links", "Liens", "bool", False),
        Param("thumbnails", "Miniatures intégrées", "bool", True),
        Param("reset_fields", "Réinitialiser les formulaires", "bool", False),
    ],
)
def sanitize(path: Path, p: dict, ctx) -> list[Path]:
    doc = ctx.open(path)
    doc.scrub(
        attached_files=bool(p["attachments"]),
        clean_pages=True,
        embedded_files=bool(p["attachments"]),
        hidden_text=bool(p["hidden_text"]),
        javascript=bool(p["javascript"]),
        metadata=bool(p["metadata"]),
        redactions=True,
        remove_links=bool(p["links"]),
        reset_fields=bool(p["reset_fields"]),
        reset_responses=True,
        thumbnails=bool(p["thumbnails"]),
        xml_metadata=bool(p["metadata"]),
    )
    dest = ctx.save(doc, ctx.output(path, "_assaini"), garbage=4, clean=True, no_new_id=False)
    doc.close()
    return [dest]


# ---------------------------------------------------------------------------
# Signatures numériques (certificats)
# ---------------------------------------------------------------------------
@tool(
    id="create_certificate",
    name="Créer un certificat de signature",
    category="security",
    icon="🪪",
    description="Génère votre certificat personnel (.p12) pour signer numériquement vos PDF.",
    mode="all",
    accepts="none",
    min_inputs=0,
    keywords="certificat p12 pfx signature numérique identité",
    output_kind="files",
    params=[
        Param("name", "Nom complet", "str", ""),
        Param("email", "E-mail", "str", ""),
        Param("org", "Organisation", "str", ""),
        Param("country", "Pays (code)", "str", "FR"),
        Param("password", "Mot de passe du certificat", "password", ""),
        Param("years", "Validité (années)", "int", 3, min=1, max=20),
        Param("folder", "Dossier d'enregistrement", "folder", ""),
    ],
)
def create_certificate(paths, p: dict, ctx) -> list[Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    if not (p.get("name") or "").strip():
        raise ToolError("Indiquez votre nom.")
    if len(p.get("password") or "") < 4:
        raise ToolError("Choisissez un mot de passe d'au moins 4 caractères pour protéger le certificat.")
    ctx.progress(0.2, "Génération de la clé RSA 3072 bits…")
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, p["name"].strip())]
    if p.get("org"):
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, p["org"].strip()))
    if p.get("country") and len(p["country"].strip()) == 2:
        attrs.append(x509.NameAttribute(NameOID.COUNTRY_NAME, p["country"].strip().upper()))
    if p.get("email"):
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, p["email"].strip()))
    name = x509.Name(attrs)
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365 * int(p["years"])))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION, ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
        .sign(key, hashes.SHA256())
    )
    data = pkcs12.serialize_key_and_certificates(
        name=p["name"].encode("utf-8"),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(p["password"].encode("utf-8")),
    )
    folder = Path(p["folder"]) if p.get("folder") else (ctx.out_dir or Path.home())
    folder.mkdir(parents=True, exist_ok=True)
    from .utils import unique_path

    dest = unique_path(folder / f"{safe_filename(p['name'])}_certificat.p12")
    dest.write_bytes(data)
    ctx.report(
        "Certificat auto-signé créé. Conservez-le précieusement avec son mot de passe.\n"
        "Il permet de prouver l'intégrité de vos documents ; pour une valeur légale qualifiée (eIDAS), "
        "utilisez un certificat délivré par une autorité de certification."
    )
    return [dest]


@tool(
    id="sign",
    name="Signer numériquement",
    category="security",
    icon="✒️",
    description="Signe le PDF avec un certificat (.p12/.pfx) : signature cryptographique visible ou invisible, horodatée.",
    keywords="signature numérique électronique certificat p12 pfx signer pades",
    params=[
        Param("cert", "Certificat (.p12 / .pfx)", "file", "", file_filter="Certificats (*.p12 *.pfx)"),
        Param("cert_pw", "Mot de passe du certificat", "password", ""),
        Param("reason", "Motif", "str", "J'approuve ce document"),
        Param("location", "Lieu", "str", ""),
        Param("visible", "Signature visible", "bool", True),
        Param("page", "Page de la signature", "pages", "fin", visible_if={"visible": True}),
        Param("position", "Position", "choice", "bottom-right", choices=POSITION_CHOICES, visible_if={"visible": True}),
        Param("certify", "Certifier (verrouille le document après signature)", "bool", False),
    ],
)
def sign(path: Path, p: dict, ctx) -> list[Path]:
    try:
        from pyhanko import stamp as hstamp
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import fields, signers
    except ImportError as exc:
        raise ToolError("Le module « pyHanko » est nécessaire pour la signature numérique (pip install pyhanko).") from exc
    if not p.get("cert"):
        raise ToolError("Choisissez votre certificat (.p12 ou .pfx). Vous pouvez en créer un avec l'outil « Créer un certificat ».")
    try:
        signer = signers.SimpleSigner.load_pkcs12(pfx_file=p["cert"], passphrase=(p.get("cert_pw") or "").encode("utf-8") or None)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Impossible de lire le certificat : {exc}") from exc
    if signer is None:
        raise ToolError("Mot de passe du certificat incorrect ou fichier invalide.")

    doc = ctx.open(path)
    tmpdir = Path(tempfile.mkdtemp(prefix="pdfb_sign_"))
    src = tmpdir / "in.pdf"
    doc.save(str(src), garbage=1, encryption=fitz.PDF_ENCRYPT_NONE)
    existing = sum(1 for page in doc for w in page.widgets() if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE)
    field_name = f"Signature{existing + 1}"
    spec = None
    if p["visible"]:
        pno = (parse_pages(p["page"], doc.page_count) or [doc.page_count - 1])[0]
        page = doc[pno]
        w, h = 200, 60
        tl = anchor_point(page.rect, p["position"], w, h, 36)
        vis = fitz.Rect(tl.x, tl.y, tl.x + w, tl.y + h) * page.derotation_matrix
        mb = page.mediabox
        # pyHanko utilise le repère PDF (origine en bas à gauche).
        box = (int(vis.x0), int(mb.height - vis.y1), int(vis.x1), int(mb.height - vis.y0))
        spec = fields.SigFieldSpec(sig_field_name=field_name, on_page=pno, box=box)
    doc.close()
    meta = signers.PdfSignatureMetadata(
        field_name=field_name,
        reason=p.get("reason") or None,
        location=p.get("location") or None,
        certify=bool(p["certify"]),
        docmdp_permissions=fields.MDPPerm.NO_CHANGES if p["certify"] else fields.MDPPerm.FILL_FORMS,
    )
    style = hstamp.TextStampStyle(stamp_text="Signé numériquement par\n%(signer)s\nLe %(ts)s", border_width=1)
    dest = ctx.output(path, "_signé")
    try:
        ctx.progress(0.5, "Signature…")
        with open(src, "rb") as inf:
            writer = IncrementalPdfFileWriter(inf, strict=False)
            pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=style, new_field_spec=spec)
            with open(dest, "wb") as outf:
                pdf_signer.sign_pdf(writer, output=outf)
    except Exception as exc:  # noqa: BLE001
        if dest.exists():
            dest.unlink()
        raise ToolError(f"La signature a échoué : {exc}") from exc
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    ctx.report(f"Document signé ({field_name}).")
    return [dest]


@tool(
    id="verify_signatures",
    name="Vérifier les signatures",
    category="security",
    icon="✅",
    description="Contrôle les signatures numériques : intégrité du document, signataire, date, couverture.",
    keywords="vérifier valider signature intégrité authenticité",
    output_kind="report",
    params=[],
)
def verify_signatures(path: Path, p: dict, ctx) -> list[Path]:
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError as exc:
        raise ToolError("Le module « pyHanko » est nécessaire (pip install pyhanko).") from exc
    lines = [f"📄 {path.name}"]
    with open(path, "rb") as fh:
        reader = PdfFileReader(fh, strict=False)
        sigs = reader.embedded_signatures
        if not sigs:
            lines.append("   Aucune signature numérique.")
        for sig in sigs:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    status = validate_pdf_signature(sig, ValidationContext(allow_fetching=False))
                cert = sig.signer_cert
                who = cert.subject.human_friendly if cert else "inconnu"
                when = status.signer_reported_dt.strftime("%d/%m/%Y %H:%M") if getattr(status, "signer_reported_dt", None) else "non indiquée"
                intact = "✅ intacte" if status.intact and status.valid else "❌ ALTÉRÉE ou invalide"
                trust = "certificat de confiance" if status.trusted else "certificat non reconnu par une autorité (auto-signé ?)"
                cov = getattr(status, "coverage", None)
                cov_txt = "couvre tout le document" if cov is not None and cov.name == "ENTIRE_FILE" else "modifications ajoutées après signature" if cov is not None else ""
                lines.append(f"   • {sig.field_name} — {intact}\n     Signataire : {who}\n     Date : {when}\n     Confiance : {trust}\n     Couverture : {cov_txt}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"   • {sig.field_name} — impossible de valider : {exc}")
    ctx.report("\n".join(lines))
    return []
