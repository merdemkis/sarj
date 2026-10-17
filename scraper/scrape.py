"""Şarj tarifelerini çekip prices.json üretir. Hata olursa eski dosyayı BOZMAZ (exit 1)."""
import json, re, sys, datetime, urllib.request
from html.parser import HTMLParser

URL = "https://www.araclo.com/elektrikli-arac-sarj-tarifeleri"  # 26 operatörün resmi tarifelerini derliyor

class P(HTMLParser):
    def __init__(s): super().__init__(); s.out = []; s.skip = 0
    def handle_starttag(s, t, a):
        a = dict(a)
        if t in ("script", "style"): s.skip += 1
        if t == "img" and "ev-charging/logos" in (a.get("src") or "") + (a.get("srcset") or ""):
            s.out.append("\x00" + (a.get("alt") or "").strip() + "\x01")
    def handle_endtag(s, t):
        if t in ("script", "style") and s.skip: s.skip -= 1
    def handle_data(s, d):
        if not s.skip and d.strip(): s.out.append(d.strip())

def parse(html):
    p = P(); p.feed(html)
    txt = " ".join(p.out)
    a, b = txt.find("listeleniyor"), txt.find("Bu istasyonlar nerede")
    if a < 0 or b < 0 or b < a: raise SystemExit("Sayfa yapısı değişmiş (başlangıç/bitiş bulunamadı)")
    txt = txt[a:b]
    tok = re.compile(r"\x00(?P<n>[^\x01]+)\x01|(?P<s>DC Hızlı Şarj|AC Yavaş Şarj|Diğer)|(?P<p>(\d{1,2}),(\d{2})\s*₺\s*/\s*kWh)")
    ops, name, sec = {}, None, None
    for m in tok.finditer(txt):
        if m.group("n"): name, sec = m.group("n"), None; ops.setdefault(name, {"DC": [], "AC": []})
        elif m.group("s"): sec = {"DC Hızlı Şarj": "DC", "AC Yavaş Şarj": "AC"}.get(m.group("s"))
        elif name and sec:
            v = float(m.group(4) + "." + m.group(5))
            if 3 <= v <= 40: ops[name][sec].append(v)
    res = {}
    for n, d in ops.items():
        r = [min(d["DC"]) if d["DC"] else None, max(d["DC"]) if d["DC"] else None,
             min(d["AC"]) if d["AC"] else None, max(d["AC"]) if d["AC"] else None]
        if any(x is not None for x in r): res[n] = r
    return res

if __name__ == "__main__":
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (kisisel-sarj-hesaplayici)"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    ops = parse(html)
    if len(ops) < 15: raise SystemExit(f"Şüpheli sonuç: sadece {len(ops)} operatör")
    json.dump({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "source": URL, "ops": ops}, open("prices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(ops), "operatör güncellendi")
