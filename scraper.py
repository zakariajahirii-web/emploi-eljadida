"""
scraper.py v5 — ANAPEC El Jadida
- Encodage UTF-8 forcé (arabe + français correct)
- Parsing précis des champs via structure HTML réelle d'ANAPEC
"""

import requests, json, re, time, os, warnings
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")
try: requests.packages.urllib3.disable_warnings()
except: pass

ROOT   = os.path.dirname(os.path.abspath(__file__))
OUT    = os.path.join(ROOT, "site", "data", "offres.json")
LOG    = os.path.join(ROOT, "logs", "scraper.log")
BASE   = "https://www.anapec.org/sigec-app-rv"
LISTE  = BASE + "/chercheurs/resultat_recherche/page:{p}/appcle:toutlesmot/ville:181/language:fr"
DETAIL = BASE + "/fr/entreprises/bloc_offre_home/{id}/resultat_recherche"
JOURS  = 20

os.makedirs(os.path.dirname(OUT), exist_ok=True)
os.makedirs(os.path.dirname(LOG), exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-MA,fr;q=0.9,ar;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

def log(msg):
    ligne = f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {msg}"
    print(ligne)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(ligne + "\n")

def get(url, essais=3):
    s = requests.Session()
    s.headers.update(HEADERS)
    try: s.get(BASE + "/", timeout=10, verify=False)
    except: pass
    for i in range(1, essais + 1):
        try:
            r = s.get(url, timeout=30, verify=False)
            r.raise_for_status()
            # Forcer l'encodage UTF-8 pour avoir l'arabe correct
            r.encoding = "utf-8"
            return r.text
        except Exception as e:
            log(f"  essai {i}: {e}")
            if i < essais: time.sleep(3)
    return None

def nettoyer(texte):
    """Nettoie le texte : supprime balises HTML, entités, espaces multiples."""
    if not texte:
        return ""
    # Décoder les entités HTML (&nbsp; &amp; etc.)
    soup = BeautifulSoup(texte, "html.parser")
    t = soup.get_text(separator=" ")
    # Supprimer les caractères de contrôle sauf \n
    t = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', t)
    # Normaliser les espaces
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()

def parse_date(s):
    try:
        d, m, y = s.strip().split("/")
        return datetime(int(y), int(m), int(d))
    except:
        return None

# ══════════════════════════════════════════════════════
#  SCRAPING LISTE
# ══════════════════════════════════════════════════════

def scraper_liste(page):
    html = get(LISTE.format(p=page))
    if not html:
        return [], True

    if page == 1:
        with open(os.path.join(ROOT, "logs", "debug.html"), "w", encoding="utf-8", errors="replace") as f:
            f.write(html)

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

        oid = m.group(1)
        cells = [nettoyer(str(td)) for td in tds]

        # Date DD/MM/YYYY
        date_str = next((c for c in cells if re.match(r'^\d{2}/\d{2}/\d{4}$', c.strip())), "")
        if date_str:
            d = parse_date(date_str)
            if d and d < date_lim:
                stop = True
                break

        # Titre = cellule la plus longue qui n'est pas date/nombre/ref
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

        ref = next((c for c in cells if re.match(r'^EL\d+', c)), "")
        nb  = next((c for c in cells if re.match(r'^\d+$', c)), "1")

        offres.append({
            "id": oid, "ref": ref, "date": date_str,
            "titre": titre, "nb": nb, "lieu": "El Jadida",
            "url": DETAIL.format(id=oid),
            "agence": "ANAPEC El Jadida",
            "secteur": "", "type_contrat": "",
            "formation": "", "date_debut": "", "description": "",
        })

    return offres, stop

# ══════════════════════════════════════════════════════
#  ENRICHISSEMENT DÉTAIL
# ══════════════════════════════════════════════════════

def enrichir(offre):
    html = get(offre["url"])
    if not html:
        return offre

    soup = BeautifulSoup(html, "html.parser")

    # ── Titre depuis <title> ───────────────────────────
    if soup.title:
        t = re.sub(r'^\(\d+\)\s*', '', soup.title.get_text(strip=True)).strip()
        if 3 < len(t) < 200:
            offre["titre"] = t

    # ── Méthode principale : chercher les blocs label/valeur ──
    # ANAPEC structure ses pages avec des patterns répétés :
    #   "Label :" suivi de la valeur sur la même ligne ou ligne suivante
    texte_brut = soup.get_text(separator="\n", strip=True)
    lignes = [l.strip() for l in texte_brut.split("\n") if l.strip()]

    def extraire_champ(label):
        """
        Cherche 'label' dans les lignes et retourne la valeur propre.
        Gère les formats : 'Label : valeur' ou 'Label\nvaleur'
        """
        for i, ligne in enumerate(lignes):
            if re.search(re.escape(label), ligne, re.IGNORECASE):
                # Format "Label : valeur" sur la même ligne
                if ':' in ligne:
                    parts = ligne.split(':', 1)
                    val = parts[1].strip() if len(parts) > 1 else ""
                    # Nettoyer les entités HTML résiduelles
                    val = re.sub(r'&[a-z]+;', ' ', val)
                    val = re.sub(r'\s+', ' ', val).strip()
                    # Vérifier que c'est une vraie valeur (pas un autre label)
                    if val and 1 < len(val) < 200 and not val.endswith(':'):
                        # Tronquer si la valeur contient un autre label
                        for stop_label in ["Lieu de travail", "Type de contrat", "Formation",
                                           "Expérience", "Poste", "Langues", "Partager",
                                           "Date de début", "Secteur", "Agence"]:
                            if stop_label.lower() in val.lower() and stop_label.lower() != label.lower():
                                val = val[:val.lower().index(stop_label.lower())].strip()
                        if val and len(val) > 1:
                            return val
                # Format "Label" seul puis valeur sur la ligne suivante
                for j in range(i + 1, min(i + 4, len(lignes))):
                    v = lignes[j].strip()
                    if v and len(v) > 1 and len(v) < 200:
                        # Vérifier que c'est pas un autre label
                        if not re.search(r'(?:Agence|Secteur|Contrat|Lieu|Formation|Expérience|Poste|Langues|Partager)\s*:', v, re.I):
                            v = re.sub(r'&[a-z]+;', ' ', v)
                            v = re.sub(r'\s+', ' ', v).strip()
                            if v and len(v) > 1:
                                return v
                        break
        return ""

    # ── Extraire chaque champ avec son label exact ────
    agence     = extraire_champ("Agence")
    secteur    = extraire_champ("Secteur d'activité")
    if not secteur:
        secteur = extraire_champ("Secteur d'activite")
    type_ctr   = extraire_champ("Type de contrat")
    date_debut = extraire_champ("Date de début")
    if not date_debut:
        date_debut = extraire_champ("Date de debut")
    lieu       = extraire_champ("Lieu de travail")

    # Formation — champ spécial : on cherche uniquement le diplôme
    # ANAPEC met: "Formation : Baccalauréat" puis "Expérience professionnelle : ..."
    formation_brute = extraire_champ("Formation")
    formation = ""
    if formation_brute:
        # Tronquer au premier marqueur parasite
        for stop in ["Expérience", "Experience", "Poste :", "Langues", "Partager", "$(", "function"]:
            idx = formation_brute.find(stop)
            if idx > 0:
                formation_brute = formation_brute[:idx].strip()
        # Nettoyer les entités et balises résiduelles
        formation = re.sub(r'&[a-z]+;', ' ', formation_brute)
        formation = re.sub(r'<[^>]+>', '', formation)
        formation = re.sub(r'\s+', ' ', formation).strip()
        # Limiter à 150 caractères
        if len(formation) > 150:
            formation = formation[:150].strip()

    # Expérience professionnelle
    experience = extraire_champ("Expérience professionnelle")
    if not experience:
        experience = extraire_champ("Experience professionnelle")

    # ── Description du profil ─────────────────────────
    description = ""
    # Chercher le bloc "Description du profil"
    for i, ligne in enumerate(lignes):
        if re.search(r'Description du profil', ligne, re.IGNORECASE):
            parts = []
            for j in range(i + 1, min(i + 15, len(lignes))):
                l = lignes[j].strip()
                # Arrêter aux sections suivantes
                if re.search(r'^(Formation|Langues|Expérience|Poste|Partager|Agence|Secteur|Type de contrat)\s*:?$', l, re.I):
                    break
                if l and len(l) > 2 and not l.startswith("$("):
                    parts.append(l)
            description = " ".join(parts)
            description = re.sub(r'&[a-z]+;', ' ', description)
            description = re.sub(r'\s+', ' ', description).strip()
            if len(description) > 500:
                description = description[:500] + "..."
            break

    # ── Appliquer les valeurs propres ─────────────────
    if agence:
        # Nettoyer l'agence : enlever le code QR et tout ce qui suit
        agence = re.sub(r'\[Scanner QR\].*$', '', agence, flags=re.I).strip()
        agence = re.sub(r'&[a-z]+;', ' ', agence)
        agence = re.sub(r'\s+', ' ', agence).strip()
        offre["agence"] = agence

    if secteur:
        # Enlever le préfixe "d'activité :"
        secteur = re.sub(r"^d[''`]activit[eé]\s*:?\s*", "", secteur, flags=re.I).strip()
        offre["secteur"] = secteur

    if type_ctr:
        # Nettoyer le type de contrat
        type_ctr = re.sub(r'\s+Lieu de travail.*$', '', type_ctr, flags=re.I).strip()
        type_ctr = re.sub(r'&[a-z]+;', ' ', type_ctr)
        type_ctr = re.sub(r'\s+', ' ', type_ctr).strip()
        # Garder uniquement la partie avant les informations parasites
        for stop in ["Formation", "Expérience", "Poste", "Langues"]:
            if stop in type_ctr:
                type_ctr = type_ctr[:type_ctr.index(stop)].strip()
        offre["type_contrat"] = type_ctr[:60] if type_ctr else ""

    if date_debut:
        offre["date_debut"] = date_debut[:20]

    if lieu:
        lieu = lieu.upper().replace("EL JADIDA", "El Jadida").replace("JORF LASFAR", "Jorf Lasfar")
        lieu = re.sub(r'\s+', ' ', lieu).strip()
        offre["lieu"] = lieu[:80]

    if formation:
        offre["formation"] = formation

    if experience:
        experience = re.sub(r'&[a-z]+;', ' ', experience)
        experience = re.sub(r'\s+', ' ', experience).strip()
        offre["experience"] = experience[:80]

    if description:
        offre["description"] = description

    return offre

# ══════════════════════════════════════════════════════
#  POINT D'ENTRÉE
# ══════════════════════════════════════════════════════

def run():
    log("=" * 45)
    log(f"SCRAPER ANAPEC El Jadida v5 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    log("=" * 45)

    offres, ids_vus = [], set()
    date_lim = datetime.now() - timedelta(days=JOURS)
    log(f"Offres depuis : {date_lim.strftime('%d/%m/%Y')}")

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
        log(f"  -> {n} offres (total: {len(offres)})")
        if stop or n == 0:
            break
        time.sleep(1.5)

    log(f"TOTAL: {len(offres)} offres")
    return offres

if __name__ == "__main__":
    offres = run()
    if offres:
        # Vérification qualité : afficher un échantillon
        log("\nEchantillon de 3 offres pour vérification :")
        for o in offres[:3]:
            log(f"  Titre     : {o['titre']}")
            log(f"  Agence    : {o['agence']}")
            log(f"  Secteur   : {o['secteur']}")
            log(f"  Contrat   : {o['type_contrat']}")
            log(f"  Lieu      : {o['lieu']}")
            log(f"  Formation : {o['formation']}")
            log(f"  Deb.      : {o['date_debut']}")
            log(f"  Desc.     : {o.get('description','')[:80]}")
            log("  ---")

        data = {
            "date_maj": datetime.now().strftime("%d/%m/%Y à %H:%M"),
            "total": len(offres),
            "offres": offres
        }
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"\nSUCCES: {len(offres)} offres sauvegardées")
    else:
        log("ECHEC: 0 offres - vérifiez logs/debug.html")
