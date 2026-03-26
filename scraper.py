import requests
from bs4 import BeautifulSoup
import json
import time
import subprocess
import os

# ----------------------------
# CONFIGURATION
# ----------------------------
URL = "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:1/appcle:toutlesmot/ville:181/language:fr"
OFFRES_JSON = "data/offres.json"
MAX_RETRIES = 5
TIMEOUT = 60
SLEEP_BETWEEN_RETRIES = 10

# ----------------------------
# FONCTION DE SCRAPING
# ----------------------------
def fetch_page(url):
    for essai in range(1, MAX_RETRIES + 1):
        try:
            print(f"[INFO] Essai {essai} pour récupérer la page...")
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            print("[INFO] Page récupérée avec succès")
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"[WARN] Essai {essai} échoué : {e}")
            if essai < MAX_RETRIES:
                print(f"[INFO] Nouvelle tentative dans {SLEEP_BETWEEN_RETRIES}s...")
                time.sleep(SLEEP_BETWEEN_RETRIES)
            else:
                print("[ERROR] Échec total de la récupération")
                return None

# ----------------------------
# EXTRACTION DES OFFRES
# ----------------------------
def parse_offres(html):
    offres = []
    soup = BeautifulSoup(html, "html.parser")
    
    # Exemple simple : adapter selon le HTML exact de la page ANAPEC
    for div in soup.select(".offre-item"):  # classe fictive, remplacer par la vraie
        titre = div.select_one(".titre").get_text(strip=True) if div.select_one(".titre") else ""
        entreprise = div.select_one(".entreprise").get_text(strip=True) if div.select_one(".entreprise") else ""
        ville = div.select_one(".ville").get_text(strip=True) if div.select_one(".ville") else ""
        date = div.select_one(".date").get_text(strip=True) if div.select_one(".date") else ""
        offres.append({
            "titre": titre,
            "entreprise": entreprise,
            "ville": ville,
            "date": date
        })
    return offres

# ----------------------------
# ÉCRITURE DU JSON
# ----------------------------
def save_offres(offres):
    os.makedirs(os.path.dirname(OFFRES_JSON), exist_ok=True)
    with open(OFFRES_JSON, "w", encoding="utf-8") as f:
        json.dump(offres, f, ensure_ascii=False, indent=4)
    print(f"[INFO] {len(offres)} offres sauvegardées dans {OFFRES_JSON}")

# ----------------------------
# PUSH AUTOMATIQUE SUR GITHUB
# ----------------------------
def push_to_github():
    try:
        subprocess.run(["git", "add", OFFRES_JSON], check=True)
        subprocess.run(["git", "commit", "-m", "Mise à jour offres automatique"], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print("[INFO] JSON mis à jour et push sur GitHub réussi")
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Push GitHub échoué : {e}")

# ----------------------------
# MAIN
# ----------------------------
def main():
    print("[INFO] DÉBUT DU SCRAPER ANAPEC EL JADIDA")
    html = fetch_page(URL)
    if html:
        offres = parse_offres(html)
        if offres:
            save_offres(offres)
            push_to_github()
        else:
            print("[WARN] Aucune offre trouvée sur la page")
    else:
        print("[ERROR] Impossible de récupérer la page, scraper annulé")

if __name__ == "__main__":
    main()
