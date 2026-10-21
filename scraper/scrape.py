"""Şarj tarifelerini çekip prices.json üretir. Hata olursa eski dosyayı BOZMAZ (exit 1)."""
import json, re, sys, os, datetime, unicodedata, urllib.request
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

URL2 = "https://sarjfiyatlari.com.tr/guncel-sarj-fiyatlari"  # 56 operatör (tek AC / tek DC fiyat)
ALIAS = {"tuncmatik": "tuncmatikcharge", "sharznet": "sharz"}
# Resmî sitesinden doğrulanmış, kaynaklardan önceliklidir: anahtar -> (gösterim adı, [dcLo,dcHi,acLo,acHi])
OVERRIDE = {"ksarj": ("K-Şarj", [11.65, 11.65, 9.15, 9.15])}  # ksarj.com/fiyatlandirma

def key(n):
    n = re.sub(r"\(.*?\)", "", n).lower()
    n = n.replace("ı", "i").replace("İ", "i")
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z0-9]", "", n)
    return ALIAS.get(n, n)

class T(HTMLParser):
    def __init__(s): super().__init__(); s.rows = []; s.row = None; s.cell = None
    def handle_starttag(s, t, a):
        if t == "tr": s.row = []
        elif t in ("td", "th") and s.row is not None: s.cell = []
    def handle_endtag(s, t):
        if t in ("td", "th") and s.cell is not None: s.row.append(" ".join(s.cell)); s.cell = None
        elif t == "tr" and s.row is not None: s.rows.append(s.row); s.row = None
    def handle_data(s, d):
        if s.cell is not None and d.strip(): s.cell.append(d.strip())

def parse2(html):
    p = T(); p.feed(html); res = {}
    pr = lambda c: (lambda m: float(m.group(1).replace(",", ".")) if m else None)(re.search(r"(\d{1,2},\d{2})\s*₺", c))
    for r in p.rows:
        if len(r) < 4: continue
        name = re.sub(r"\bSponsorlu\b", "", r[1]).strip()
        ac, dc = pr(r[2]), pr(r[3])
        if name and (ac or dc) and all(v is None or 3 <= v <= 40 for v in (ac, dc)):
            res[name] = [dc, dc, ac, ac]
    return res

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kisisel-sarj-hesaplayici)"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

def main():
    try: old = json.load(open("prices.json", encoding="utf-8"))
    except Exception: old = {"ops": {}, "upd": {}}
    ops, upd, src, now = dict(old.get("ops", {})), dict(old.get("upd", {})), dict(old.get("src", {})), datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    idx = {key(n): n for n in ops}
    got = {}
    for label, fn, url, minimum in (("araclo", parse, URL, 15), ("sarjfiyatlari", parse2, URL2, 20)):
        try:
            r = fn(get(url))
            if len(r) < minimum: raise ValueError(f"sadece {len(r)} operatör")
            got[label] = r; print(label, len(r), "operatör")
        except Exception as e: print("UYARI:", label, "alınamadı:", e)
    if not got: raise SystemExit("Hiçbir kaynaktan veri alınamadı; eski dosya korundu")
    # araclo (resmî tarifelerden, aralıklı) önce, sarjfiyatlari sadece eksikleri doldurur
    for label in ("araclo", "sarjfiyatlari"):
        for n, v in got.get(label, {}).items():
            k = key(n)
            if label == "sarjfiyatlari" and k in idx and src.get(idx[k]) == "araclo" and "araclo" in got: continue
            nm = idx.get(k, n); ops[nm] = v; idx[k] = nm; upd[nm] = now; src[nm] = label
    for k, (nm, v) in OVERRIDE.items():
        old_nm = idx.get(k)
        if old_nm and old_nm != nm: ops.pop(old_nm, None); upd.pop(old_nm, None); src.pop(old_nm, None)
        ops[nm] = v; idx[k] = nm; upd[nm] = now; src[nm] = "resmî site"
    if len(ops) < 15: raise SystemExit("Şüpheli sonuç; eski dosya korundu")
    json.dump({"updated": now, "source": "araclo.com + sarjfiyatlari.com.tr", "ops": dict(sorted(ops.items())), "upd": upd, "src": src},
              open("prices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(ops), "operatör yazıldı")

if __name__ == "__main__": main()
