"""{{Alan}} yer tutucularını firma verisiyle doldurma."""
import re

PLACEHOLDER_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")


def normalize_key(name):
    """Büyük/küçük harf ve boşluk farkını yok sayar: '{{ yetkili }}' == '{{Yetkili}}'."""
    return "".join(str(name).replace("İ", "i").split()).casefold()


def contact_fields(contact):
    """Bir firmanın şablonda kullanılabilecek tüm alanları."""
    fields = dict(contact.get("extra") or {})
    fields["Email"] = contact.get("email", "")
    fields["Firma"] = contact.get("firma", "")
    fields["Yetkili"] = contact.get("yetkili", "")
    return fields


def placeholders(text):
    """Metindeki yer tutucu adları (tekrarsız, sırayla)."""
    names = []
    for match in PLACEHOLDER_RE.finditer(text or ""):
        if match.group(1) not in names:
            names.append(match.group(1))
    return names


def render(text, fields):
    """Metni doldurur. (doldurulmuş metin, doldurulamayan alan adları) döner.

    Doldurulamayan yer tutucu metinde olduğu gibi bırakılır ki önizlemede görünsün.
    """
    lookup = {normalize_key(k): v for k, v in fields.items()}
    missing = []

    def replace(match):
        name = match.group(1)
        value = lookup.get(normalize_key(name))
        if value is None or str(value).strip() == "":
            if name not in missing:
                missing.append(name)
            return match.group(0)
        return str(value)

    return PLACEHOLDER_RE.sub(replace, text or ""), missing


def render_mail(subject, body, contact):
    """Konu ve gövdeyi bir firma için doldurur. (konu, gövde, eksik alanlar) döner."""
    fields = contact_fields(contact)
    filled_subject, missing_subject = render(subject, fields)
    filled_body, missing_body = render(body, fields)
    missing = missing_subject + [m for m in missing_body if m not in missing_subject]
    return filled_subject, filled_body, missing
