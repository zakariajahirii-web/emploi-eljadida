"""
scraper.py — ANAPEC El Jadida
Tourne automatiquement chaque jour via GitHub Actions
Sauvegarde : data/offres.json
"""

import requests, json, re, time, os, warnings
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
try: requests.packages.urllib3.disable_warnings()
except: pass

# Sur GitHub Actions, le dossier courant est la racine du repo
ROOT   = os.path.dirname(os.path.abspath(__file__))
OUT    = os.path.join(ROOT, "data", "offres.json")
BASE   = "https://www.anapec.org/sigec-app-rv"
LISTE  = BASE + "/chercheurs/resultat_recherche/page:{p}/appcle:toutlesmot/ville:181/language:fr"
DETAIL = BASE + "/fr/entreprises/bloc_offre_home/{id}/resultat_recherche"
JOURS  = 20

os.makedirs(os.path.dirname(OUT), exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

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
    t = re.sub(r'[ \t]+', ' ', t)
    return t.strip()

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
            (c for c in cells
             if 5 < len(c) < 200
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
            "date": date_str,
            "titre": titre,
            "nb": next((c for c in cells if re.match(r'^\d+$', c)), "1"),
            "lieu": "El Jadida",
            "url": DETAIL.format(id=oid),
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

    # Titre depuis <title>
    if soup.title:
        t = re.sub(r'^\(\d+\)\s*', '', soup.title.get_text(strip=True)).strip()
        if 3 < len(t) < 200:
            offre["titre"] = t

    # Texte ligne par ligne
    lignes = [l.strip() for l in soup.get_text(separator="\n", strip=True).split("\n") if l.strip()]

    def extraire(label):
        for i, ligne in enumerate(lignes):
            if re.search(re.escape(label), ligne, re.IGNORECASE):
                # Valeur sur la même ligne après ":"
                if ':' in ligne:
                    val = ligne.split(':', 1)[1].strip()
                    val = re.sub(r'&[a-z]+;', ' ', val)
                    val = re.sub(r'\s+', ' ', val).strip()
                    # Couper aux labels parasites
                    for stop in ["Lieu de travail", "Type de contrat", "Formation",
                                 "Expérience", "Poste", "Langues", "Partager",
                                 "Date de début", "Secteur", "Agence"]:
                        if stop.lower() in val.lower() and stop.lower() != label.lower():
                            val = val[:val.lower().index(stop.lower())].strip()
                    if val and 1 < len(val) < 200:
                        return val
                # Valeur sur la ligne suivante
                for j in range(i + 1, min(i + 4, len(lignes))):
                    v = lignes[j].strip()
                    if v and 1 < len(v) < 200:
                        if not re.search(r'(?:Agence|Secteur|Contrat|Lieu|Formation|Expérience|Poste|Langues|Partager)\s*:', v, re.I):
                            v = re.sub(r'&[a-z]+;', ' ', v)
                            return re.sub(r'\s+', ' ', v).strip()
                        break
        return ""

    # Extraire chaque champ
    agence     = extraire("Agence")
    secteur    = extraire("Secteur d'activité") or extraire("Secteur d'activite")
    type_ctr   = extraire("Type de contrat")
    date_debut = extraire("Date de début") or extraire("Date de debut")
    lieu       = extraire("Lieu de travail")
    formation  = extraire("Formation")
    experience = extraire("Expérience professionnelle") or extraire("Experience professionnelle")

    # Nettoyer et appliquer
    if agence:
        agence = re.sub(r'\[Scanner QR\].*$', '', agence, flags=re.I)
        agence = re.sub(r'&[a-z]+;|\s+', ' ', agence).strip()
        offre["agence"] = agence[:100]

    if secteur:
        secteur = re.sub(r"^d[''`]activit[eé]\s*:?\s*", "", secteur, flags=re.I)
        offre["secteur"] = re.sub(r'\s+', ' ', secteur).strip()[:100]

    if type_ctr:
        for stop in ["Formation", "Expérience", "Poste", "Langues", "Lieu"]:
            if stop in type_ctr:
                type_ctr = type_ctr[:type_ctr.index(stop)].strip()
        type_ctr = re.sub(r'&[a-z]+;|\s+', ' ', type_ctr).strip()
        offre["type_contrat"] = type_ctr[:80]

    if date_debut:
        offre["date_debut"] = date_debut[:20]

    if lieu:
        lieu = lieu.upper().replace("EL JADIDA", "El Jadida").replace("JORF LASFAR", "Jorf Lasfar")
        offre["lieu"] = re.sub(r'\s+', ' ', lieu).strip()[:80]

    if formation:
        for stop in ["Expérience", "Experience", "Poste :", "Langues", "$(", "function"]:
            if stop in formation:
                formation = formation[:formation.index(stop)].strip()
        formation = re.sub(r'&[a-z]+;|<[^>]+>|\s+', ' ', formation).strip()
        offre["formation"] = formation[:150]

    if experience:
        experience = re.sub(r'&[a-z]+;|\s+', ' ', experience).strip()
        offre["experience"] = experience[:80]

    # Description du profil
    for i, ligne in enumerate(lignes):
        if re.search(r'Description du profil', ligne, re.IGNORECASE):
            parts = []
            for j in range(i + 1, min(i + 15, len(lignes))):
                l = lignes[j].strip()
                if re.search(r'^(Formation|Langues|Expérience|Poste|Partager|Agence|Secteur|Type de contrat)\s*:?$', l, re.I):
                    break
                if l and len(l) > 2 and not l.startswith("$("):
                    parts.append(l)
            desc = " ".join(parts)
            desc = re.sub(r'&[a-z]+;|\s+', ' ', desc).strip()
            if desc:
                offre["description"] = desc[:500]
            break

    return offre

def run():
    log(f"SCRAPER ANAPEC El Jadida — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    log(f"Offres des {JOURS} derniers jours")

    offres, ids_vus = [], set()

    for page in range(1, 30):
        log(f"Page {page}...")
        liste, stop = scraper_liste(page)
        n = 0
        for o in liste:
            if o["id"] not in ids_vus:
                ids_vus.add(o["id"])
                log(f"  + [{o['date']}] {o['titre'][:55]}")
                o = enrichir(o)
                offres.append(o)
                n += 1
                time.sleep(0.8)
        log(f"  → {n} offres (total: {len(offres)})")
        if stop or n == 0:
            break
        time.sleep(1.5)

    log(f"TOTAL: {len(offres)} offres")
    return offres

if __name__ == "__main__":
    offres = run()
    if offres:
        data = {
            "date_maj": datetime.now().strftime("%d/%m/%Y à %H:%M"),
            "total": len(offres),
            "offres": offres
        }
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"✓ Sauvegardé : {OUT} ({len(offres)} offres)")

        # Afficher un résumé
        log("\nRésumé des 3 premières offres :")
        for o in offres[:3]:
            log(f"  [{o['date']}] {o['titre'][:40]}")
            log(f"    Contrat : {o['type_contrat']}")
            log(f"    Formation : {o['formation']}")
            log(f"    Lieu : {o['lieu']}")
    else:
        log("✗ ECHEC : 0 offres collectées")
        exit(1)
