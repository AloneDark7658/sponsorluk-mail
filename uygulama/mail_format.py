"""Mail içeriği yardımcıları: ek dosya listesi ve imza (düz metin, logo varsa HTML)."""
import html
import json
import re
from pathlib import Path

from config import BLOCKED_EXTENSIONS, ICON_DIR, MAX_TOTAL_ATTACHMENT_MB

LOGO_CID = "imza-logo"
DEFAULT_LOGO_WIDTH = 150
LINK_RE = re.compile(r"(https?://[^\s<>\"]+|www\.[^\s<>\"]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)")
TRAILING_PUNCTUATION = ".,;:!?)"


# ---------- Ekler ----------

def parse_attachments(value):
    """Kayıtlı değeri dosya listesine çevirir. Eski sürümlerde tek dosya yolu saklanıyordu."""
    if not value:
        return []
    if value.lstrip().startswith("["):
        try:
            return [p for p in json.loads(value) if p]
        except ValueError:
            return []
    return [value]


def dump_attachments(paths):
    return json.dumps(list(paths), ensure_ascii=False)


def size_mb(path):
    try:
        return Path(path).stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


def total_size_mb(paths):
    return sum(size_mb(p) for p in paths)


def blocked(path):
    return Path(path).suffix.lower() in BLOCKED_EXTENSIONS


def attachment_problems(paths):
    """Gönderimi engelleyecek sorunlar (kullanıcıya gösterilecek Türkçe cümleler)."""
    problems = []
    missing = [Path(p).name for p in paths if not Path(p).exists()]
    if missing:
        problems.append("Bulunamayan ek dosya: " + ", ".join(missing) + " (taşınmış ya da silinmiş olabilir)")
    bad = [Path(p).name for p in paths if blocked(p)]
    if bad:
        problems.append("Gmail bu dosya türlerini güvenlik nedeniyle engelliyor: " + ", ".join(bad))
    total = total_size_mb(paths)
    if total > MAX_TOTAL_ATTACHMENT_MB:
        problems.append(f"Eklerin toplamı {total:.1f} MB; en fazla {MAX_TOTAL_ATTACHMENT_MB} MB olabilir. "
                        "Büyük dosyaları sıkıştırın ya da Google Drive linki olarak metne ekleyin.")
    return problems


# ---------- İmza ----------
#
# İki tür imza var:
#   "card": kartvizit şablonu (solda logo | sağda ad, unvan, iletişim, sosyal medya ikonları) - HTML
#   "text": serbest düz metin (isteğe bağlı logo altta)

SIGNATURE_CARD = "card"
SIGNATURE_TEXT = "text"
ICON_SIZE = 26
# (anahtar, form etiketi)
CARD_FIELDS = [
    ("name", "Ad Soyad"), ("title", "Unvan"), ("phone", "Telefon"), ("email", "E-posta"),
    ("address", "Adres"), ("website", "Web sitesi"),
]
SOCIAL_FIELDS = [("x", "X (Twitter)"), ("instagram", "Instagram"), ("facebook", "Facebook"), ("linkedin", "LinkedIn")]
CARD_DEFAULTS = {"address": "İTÜ Maçka Kampüsü", "website": "yatirimkulubu.net"}


def load_card(db):
    try:
        card = json.loads(db.get_setting("signature_card") or "{}")
    except ValueError:
        card = {}
    return {key: str(card.get(key, CARD_DEFAULTS.get(key, ""))).strip()
            for key, _ in CARD_FIELDS + SOCIAL_FIELDS}


def card_plain_text(card):
    """Kartvizitin düz metin hâli (HTML gösteremeyen programlar ve önizleme için)."""
    lines = [card["name"], card["title"]]
    for prefix, key in (("m", "phone"), ("e", "email"), ("a", "address")):
        if card[key]:
            lines.append(f"{prefix}: {card[key]}")
    lines.append(card["website"])
    return "\n".join(line for line in lines if line)


def load_signature(db):
    """Ayarlardaki imza. Kapalıysa ya da boşsa None."""
    if db.get_setting("signature_enabled", "1") != "1":
        return None
    logo = db.get_setting("signature_logo") or None
    try:
        width = int(db.get_setting("signature_logo_width", DEFAULT_LOGO_WIDTH))
    except (TypeError, ValueError):
        width = DEFAULT_LOGO_WIDTH
    if db.get_setting("signature_mode", SIGNATURE_CARD) == SIGNATURE_CARD:
        card = load_card(db)
        if not card["name"]:
            return None
        return {"mode": SIGNATURE_CARD, "card": card, "text": card_plain_text(card), "logo": logo,
                "logo_width": width}
    text = (db.get_setting("signature_text") or "").strip()
    if not text and not logo:
        return None
    return {"mode": SIGNATURE_TEXT, "text": text, "logo": logo, "logo_width": width}


def _url(value):
    value = value.strip()
    return value if value.startswith(("http://", "https://")) else "https://" + value


def signature_images(signature):
    """Maile gömülecek görseller: [(cid, dosya yolu)]"""
    if not signature:
        return []
    images = [(LOGO_CID, signature["logo"])] if signature.get("logo") else []
    if signature.get("mode") == SIGNATURE_CARD:
        images += [(f"imza-{key}", str(ICON_DIR / f"{key}.png"))
                   for key, _ in SOCIAL_FIELDS if signature["card"].get(key)]
    return images


def signature_problems(signature):
    problems = []
    for cid, path in signature_images(signature):
        if not Path(path).exists():
            what = "İmza logosu" if cid == LOGO_CID else "İmza ikonu"
            problems.append(f"{what} bulunamadı: {Path(path).name} (İmza ayarlarından kontrol edin)")
    return problems


def plain_body(body, signature):
    """Düz metin gövde + imza."""
    body = body.rstrip()
    if signature and signature.get("text"):
        return f"{body}\n\n{signature['text']}"
    return body


def preview_body(body, signature):
    """Önizlemede gösterilecek hâl (görseller için yer tutucu satırlarla)."""
    text = plain_body(body, signature)
    if signature and signature.get("logo"):
        text += f"\n[Logo: {Path(signature['logo']).name}]"
    if signature and signature.get("mode") == SIGNATURE_CARD:
        socials = [label for key, label in SOCIAL_FIELDS if signature["card"].get(key)]
        if socials:
            text += "\n[Sosyal medya ikonları: " + ", ".join(socials) + "]"
        text += "\n(Kartvizit düzeni gerçek mailde görünür; 'İmza ayarları → Tarayıcıda önizle')"
    return text


def needs_html(signature):
    """Kartvizit ve logo ancak HTML mailde gösterilebilir."""
    return bool(signature and (signature.get("logo") or signature.get("mode") == SIGNATURE_CARD))


def _linkify(escaped_text):
    def replace(match):
        token = match.group(0)
        trailing = ""
        while token and token[-1] in TRAILING_PUNCTUATION:
            trailing = token[-1] + trailing
            token = token[:-1]
        if token.startswith(("http://", "https://")):
            href = token
        elif "@" in token and not token.startswith("www."):
            href = "mailto:" + token
        else:
            href = "https://" + token
        return f'<a href="{href}">{token}</a>{trailing}'

    return LINK_RE.sub(replace, escaped_text)


def _to_html(text):
    return _linkify(html.escape(text)).replace("\n", "<br>\n")


def card_html(signature, image_src=None):
    """Kartvizit imzası (mail programlarında tutarlı görünsün diye tablo + satır içi stil).

    image_src(cid) -> görselin adresi; mailde 'cid:...', tarayıcı önizlemesinde dosya yolu.
    """
    image_src = image_src or (lambda cid: f"cid:{cid}")
    card = signature["card"]
    e = html.escape
    font = "font-family:Arial,Helvetica,sans-serif;color:#000000;"
    rows = []
    for prefix, key in (("m", "phone"), ("e", "email"), ("a", "address")):
        value = card[key]
        if not value:
            continue
        if key == "email":
            value_html = f'<a href="mailto:{e(value)}" style="color:#1155cc;text-decoration:underline">{e(value)}</a>'
        elif key == "phone":
            value_html = f'<a href="tel:{e(value.replace(" ", ""))}" style="color:#000000;text-decoration:none">{e(value)}</a>'
        else:
            value_html = e(value)
        rows.append(f'<tr><td style="{font}font-size:13px;padding:4px 8px 4px 0">{prefix}:</td>'
                    f'<td style="{font}font-size:13px;padding:4px 0">{value_html}</td></tr>')
    website = ""
    if card["website"]:
        website = (f'<div style="{font}font-size:13px;padding-top:4px"><a href="{e(_url(card["website"]))}" '
                   f'style="color:#1155cc;text-decoration:underline">{e(card["website"])}</a></div>')
    icons = "".join(
        f'<a href="{e(_url(card[key]))}" style="text-decoration:none;margin-right:6px">'
        f'<img src="{image_src("imza-" + key)}" width="{ICON_SIZE}" height="{ICON_SIZE}" alt="{e(label)}" '
        f'style="border:0;vertical-align:middle"></a>'
        for key, label in SOCIAL_FIELDS if card.get(key)
    )
    logo_cell = ""
    if signature.get("logo"):
        logo_cell = (f'<td style="padding:0 22px 0 0;vertical-align:middle">'
                     f'<img src="{image_src(LOGO_CID)}" width="{signature["logo_width"]}" alt="logo" '
                     f'style="display:block;border:0"></td>')
        border = "border-left:1px solid #000000;padding:4px 0 4px 18px;"
    else:
        border = "padding:4px 0;"
    return (
        '<table cellpadding="0" cellspacing="0" border="0" style="margin-top:22px;border-collapse:collapse"><tr>'
        f'{logo_cell}<td style="{border}vertical-align:top">'
        f'<div style="{font}font-size:14px;font-weight:bold">{e(card["name"])}</div>'
        + (f'<div style="{font}font-size:13px;padding-top:6px">{e(card["title"])}</div>' if card["title"] else "")
        + '<div style="border-top:1px solid #999999;margin:10px 0 8px 0;width:220px;font-size:0;line-height:0">&nbsp;</div>'
        + f'<table cellpadding="0" cellspacing="0" border="0">{"".join(rows)}</table>'
        + website
        + (f'<div style="padding-top:14px">{icons}</div>' if icons else "")
        + "</td></tr></table>"
    )


def html_body(body, signature, image_src=None):
    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222222">',
        _to_html(body.rstrip()),
        "</div>",
    ]
    if signature and signature.get("mode") == SIGNATURE_CARD:
        parts.append(card_html(signature, image_src))
    elif signature:
        src = (image_src or (lambda cid: f"cid:{cid}"))(LOGO_CID)
        parts.append('<div style="margin-top:18px;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#555555">')
        if signature.get("text"):
            parts.append(_to_html(signature["text"]))
        if signature.get("logo"):
            parts.append(f'<div style="margin-top:8px"><img src="{src}" width="{signature["logo_width"]}" '
                         'alt="logo" style="display:block;border:0"></div>')
        parts.append("</div>")
    return "<html><body>" + "".join(parts) + "</body></html>"


def preview_html_file(signature, body="Sayın Yetkili,\n\nMail metniniz burada yer alır.\n\nSaygılarımızla"):
    """İmzayı tarayıcıda görmek için geçici bir HTML dosyası yazar, yolunu döner."""
    import tempfile
    images = dict(signature_images(signature))
    page = html_body(body, signature, lambda cid: Path(images[cid]).resolve().as_uri() if cid in images else "")
    path = Path(tempfile.gettempdir()) / "imza_onizleme.html"
    path.write_text(page, encoding="utf-8")
    return path
