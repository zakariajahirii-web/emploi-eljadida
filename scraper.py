"""
scraper.py — ANAPEC El Jadida
A mettre a la RACINE du repo GitHub: emploi-eljadida
S'execute automatiquement via GitHub Actions chaque matin
"""

import requests, json, re, time, warnings, base64, os
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
try: requests.packages.urllib3.disable_warnings()
except: pass

# Lus depuis les secrets GitHub Actions
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER  = os.environ.get("GITHUB_USER",  "zakariajahirii-web")
GITHUB_REPO  = os.environ.get("GITHUB_REPO",  "emploi-eljadida")

BASE   = "https://www.anapec.org/sigec-app-rv"
LISTE  = BASE + "/chercheurs/resultat_recherche/page:{p}/appcle:toutlesmot/ville:181/language:fr"
DETAIL = BASE + "/fr/entreprises/bloc_offre_home/{id}/resultat_recherche"
JOURS  = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get(url, essais=3):
    s = requests.Session()
    s.headers.update(HEADERS)
    try: s.get(BASE + "/", timeout=10, verify=False)
    except: pass
    for i in range(1, essais + 1):
        try:
            r = s.get(url, timeout=30, verify=False)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except Exception as e:
            log(f"  essai {i}: {e}")
            if i < essais: time.sleep(3)
    return None

def nettoyer(txt):
    if not txt: return ""
    soup = BeautifulSoup(str(txt), "html.parser")
    t = soup.get_text(separator=" ")
    return re.sub(r'[ \t]+', ' ', t).strip()

def parse_date(s):
    try:
        d, m, y = s.strip().split("/")
        return datetime(int(y), int(m), int(d))
    except:
        return None

def scraper_liste(page):
    html = get(LISTE.format(p=page))
    if not html:
        return [], True

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tbody tr")
    date_lim = datetime.now() - timedelta(days=JOURS)
    offres, stop = [], False

    for tr in rows:
        tds = tr.find_all("td")
        link = tr.find("a", href=re.compile(r"/bloc_offre_home/\d+/"))
        if not link or len(tds) < 4:
            continue
        m = re.search(r"/bloc_offre_home/(\d+)/", link["href"])
        if not m:
            continue

        oid   = m.group(1)
        cells = [nettoyer(str(td)) for td in tds]

        date_str = next((c for c in cells if re.match(r'^\d{2}/\d{2}/\d{4}$', c.strip())), "")
        if date_str:
            d = parse_date(date_str)
            if d and d < date_lim:
                stop = True
                break

        titre = max(
            (c for c in cells if 5 < len(c) < 200
             and not re.match(r'^\d+$', c)
             and not re.match(r'^\d{2}/\d{2}/\d{4}$', c)
             and not c.startswith("EL")),
            key=len, default=""
        )
        if not titre:
            continue

        offres.append({
            "id": oid,
            "ref": next((c for c in cells if re.match(r'^EL\d+', c)), ""),
            "date": date_str, "titre": titre,
            "nb": next((c for c in cells if re.match(r'^\d+$', c)), "1"),
            "lieu": "El Jadida", "url": DETAIL.format(id=oid),
            "agence": "ANAPEC El Jadida",
            "secteur": "", "type_contrat": "",
            "formation": "", "experience": "",
            "date_debut": "", "description": "",
        })

    return offres, stop

def enrichir(offre):
    html = get(offre["url"])
    if not html:
        return offre

    soup = BeautifulSoup(html, "html.parser")
    if soup.title:
        t = re.sub(r'^\(\d+\)\s*', '', soup.title.get_text(strip=True)).strip()
        if 3 < len(t) < 200:
            offre["titre"] = t

    lignes = [l.strip() for l in soup.get_text(separator="\n", strip=True).split("\n") if l.strip()]

    def extraire(label):
        for i, ligne in enumerate(lignes):
            if re.search(re.escape(label), ligne, re.IGNORECASE):
                if ':' in ligne:
                    val = ligne.split(':', 1)[1].strip()
                    val = re.sub(r'&[a-z]+;|\s+', ' ', val).strip()
                    for stop in ["Lieu de travail","Type de contrat","Formation",
                                 "Expérience","Poste","Langues","Partager","Date de début","Secteur","Agence"]:
                        if stop.lower() in val.lower() and stop.lower() != label.lower():
                            val = val[:val.lower().index(stop.lower())].strip()
                    if val and 1 < len(val) < 200:
                        return val
                for j in range(i+1, min(i+4, len(lignes))):
                    v = lignes[j].strip()
                    if v and 1 < len(v) < 200:
                        if not re.search(r'(?:Agence|Secteur|Contrat|Lieu|Formation|Expérience|Poste|Langues|Partager)\s*:', v, re.I):
                            return re.sub(r'&[a-z]+;|\s+', ' ', v).strip()
                        break
        return ""

    agence     = extraire("Agence")
    secteur    = extraire("Secteur d'activité") or extraire("Secteur d'activite")
    type_ctr   = extraire("Type de contrat")
    date_debut = extraire("Date de début") or extraire("Date de debut")
    lieu       = extraire("Lieu de travail")
    formation  = extraire("Formation")
    experience = extraire("Expérience professionnelle") or extraire("Experience professionnelle")

    if agence:
        agence = re.sub(r'\[Scanner QR\].*$', '', agence, flags=re.I)
        offre["agence"] = re.sub(r'&[a-z]+;|\s+', ' ', agence).strip()[:100]
    if secteur:
        offre["secteur"] = re.sub(r"^d[''`]activit[eé]\s*:?\s*", "", secteur, flags=re.I).strip()[:100]
    if type_ctr:
        for stop in ["Formation","Expérience","Poste","Langues","Lieu"]:
            if stop in type_ctr:
                type_ctr = type_ctr[:type_ctr.index(stop)].strip()
        offre["type_contrat"] = re.sub(r'&[a-z]+;|\s+', ' ', type_ctr).strip()[:80]
    if date_debut:
        offre["date_debut"] = date_debut[:20]
    if lieu:
        lieu = lieu.upper().replace("EL JADIDA","El Jadida").replace("JORF LASFAR","Jorf Lasfar")
        offre["lieu"] = re.sub(r'\s+',' ', lieu).strip()[:80]
    if formation:
        for stop in ["Expérience","Experience","Poste :","Langues","$(","function"]:
            if stop in formation:
                formation = formation[:formation.index(stop)].strip()
        offre["formation"] = re.sub(r'&[a-z]+;|<[^>]+>|\s+', ' ', formation).strip()[:150]
    if experience:
        offre["experience"] = re.sub(r'&[a-z]+;|\s+', ' ', experience).strip()[:80]

    for i, ligne in enumerate(lignes):
        if re.search(r'Description du profil', ligne, re.IGNORECASE):
            parts = []
            for j in range(i+1, min(i+15, len(lignes))):
                l = lignes[j].strip()
                if re.search(r'^(Formation|Langues|Expérience|Poste|Partager|Agence|Secteur|Type de contrat)\s*:?$', l, re.I):
                    break
                if l and len(l) > 2 and not l.startswith("$("):
                    parts.append(l)
            desc = re.sub(r'&[a-z]+;|\s+', ' ', " ".join(parts)).strip()
            if desc:
                offre["description"] = desc[:500]
            break

    return offre


def publier_github(offres):
    if not GITHUB_TOKEN:
        log("Token GitHub non configuré — publication ignorée")
        return False

    data = {
        "date_maj": datetime.now().strftime("%d/%m/%Y à %H:%M"),
        "total": len(offres),
        "offres": offres
    }
    contenu_b64 = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    api_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/data/offres.json"
    headers_gh = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    sha = None
    try:
        r = requests.get(api_url, headers=headers_gh, timeout=15)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except:
        pass

    payload = {
        "message": f"ANAPEC El Jadida — {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "content": contenu_b64,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(api_url, headers=headers_gh, json=payload, timeout=30)
        if r.status_code in (200, 201):
            log(f"GitHub mis a jour : {len(offres)} offres")
            log(f"Site : https://{GITHUB_USER}.github.io/{GITHUB_REPO}")
            return True
        else:
            log(f"Erreur GitHub {r.status_code}: {r.text[:300]}")
            return False
    except Exception as e:
        log(f"Erreur GitHub: {e}")
        return False


if __name__ == "__main__":
    log(f"SCRAPER ANAPEC El Jadida — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    offres, ids_vus = [], set()

    for page in range(1, 30):
        log(f"Page {page}...")
        liste, stop = scraper_liste(page)
        n = 0
        for o in liste:
            if o["id"] not in ids_vus:
                ids_vus.add(o["id"])
                log(f"  + [{o['date']}] {o['titre'][:50]}")
                o = enrichir(o)
                offres.append(o)
                n += 1
                time.sleep(0.8)
        log(f"  -> {n} (total: {len(offres)})")
        if stop or n == 0:
            break
        time.sleep(1.5)

    if offres:
        os.makedirs("data", exist_ok=True)
        data = {
            "date_maj": datetime.now().strftime("%d/%m/%Y à %H:%M"),
            "total": len(offres),
            "offres": offres
        }
        with open("data/offres.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"TOTAL: {len(offres)} offres sauvegardees")
        publier_github(offres)
    else:
        log("ECHEC: 0 offres trouvees")
        raise SystemExit(1)
