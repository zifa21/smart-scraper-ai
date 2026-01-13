import streamlit as st
import os
import json
import pandas as pd
from bs4 import BeautifulSoup
import requests
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIGURATION ---
st.set_page_config(page_title="Super Scraper AI", page_icon="🤖", layout="wide")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY") if hasattr(st, 'secrets') else os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error("⚠️ GROQ_API_KEY manquante")
    st.stop()

class IntelligentScraper:
    def __init__(self):
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    
    def call_ai(self, prompt, max_tokens=8000, temperature=0.1):
        """Appelle Groq avec des paramètres optimisés"""
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "Tu es le meilleur extracteur de données e-commerce au monde. Tu ne rates JAMAIS un produit et tu extrais TOUTES les informations disponibles avec une précision chirurgicale."},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=120)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            st.error(f"❌ Erreur API: {str(e)}")
            return None
    
    def fetch_page(self, url):
        """Récupère une page avec retry"""
        for attempt in range(3):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except Exception as e:
                if attempt == 2:
                    st.warning(f"⚠️ Échec après 3 tentatives: {url}")
                    return None
                time.sleep(1)
        return None
    
    def ai_detect_product_urls(self, html, base_url):
        """L'IA détecte TOUTES les URLs de produits"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extraction de tous les liens
        all_links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href')
            if href and href not in ['#', 'javascript:void(0)']:
                # Normalisation URL
                if href.startswith('//'):
                    href = 'https:' + href
                elif href.startswith('/'):
                    domain = '/'.join(base_url.split('/')[:3])
                    href = domain + href
                elif not href.startswith('http'):
                    domain = '/'.join(base_url.split('/')[:3])
                    href = domain + '/' + href
                
                # Contexte du lien
                text = a.get_text(strip=True)
                parent_text = a.parent.get_text(strip=True)[:200] if a.parent else ""
                img = a.find('img')
                has_image = img is not None
                
                all_links.append({
                    'url': href,
                    'text': text[:100],
                    'context': parent_text,
                    'has_image': has_image
                })
        
        # Dédoublonnage
        unique_links = {}
        for link in all_links:
            url = link['url']
            if url not in unique_links:
                unique_links[url] = link
        
        links_data = list(unique_links.values())[:200]  # Max 200 liens pour l'IA
        
        # L'IA analyse et filtre les URLs produits
        prompt = f"""Analyse ces liens d'une page e-commerce et identifie TOUS les liens de PAGES PRODUIT individuelles.

URL de base: {base_url}

LIENS DÉTECTÉS:
{json.dumps(links_data[:100], indent=2, ensure_ascii=False)}

MISSION:
Retourne un JSON array contenant UNIQUEMENT les URLs qui pointent vers des PAGES PRODUIT individuelles (pas les catégories, filtres, CGV, etc.).

Format de réponse (STRICTEMENT ce format):
["url1", "url2", "url3", ...]

CRITÈRES pour identifier une page produit:
- URL contient souvent: /produit/, /product/, /p/, /item/, un code produit, un nom de produit
- Texte du lien = nom de produit
- Le lien a une image
- Évite: /categorie/, /marque/, /filtre/, /panier/, /compte/, /cgv/

Retourne UNIQUEMENT le JSON array des URLs:"""

        result = self.call_ai(prompt, max_tokens=4000)
        
        if result:
            try:
                result = result.strip()
                if "```json" in result:
                    result = result.split("```json")[1].split("```")[0]
                elif "```" in result:
                    result = result.split("```")[1].split("```")[0]
                
                # Cherche le JSON array
                json_match = re.search(r'\[.*?\]', result, re.DOTALL)
                if json_match:
                    result = json_match.group(0)
                
                product_urls = json.loads(result)
                
                if isinstance(product_urls, list):
                    # Validation finale
                    valid_urls = [url for url in product_urls if isinstance(url, str) and url.startswith('http')]
                    return valid_urls
            except:
                st.warning("⚠️ L'IA n'a pas pu parser les URLs, passage en mode automatique...")
        
        # Fallback: détection automatique basique
        product_urls = []
        for link in links_data:
            url = link['url']
            # Patterns courants de pages produits
            if any(pattern in url.lower() for pattern in ['/produit/', '/product/', '/p/', '/item/', '/detail/']):
                product_urls.append(url)
            elif link['has_image'] and len(link['text']) > 5 and 'categorie' not in url.lower():
                product_urls.append(url)
        
        return list(set(product_urls))[:100]  # Max 100 produits
    
    def ai_extract_product_details(self, html, url):
        """L'IA extrait TOUTES les infos d'une page produit"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Supprime le bruit
        for tag in soup(["script", "style", "nav", "footer", "header", "svg"]):
            tag.decompose()
        
        # Extraction du contenu structuré
        body_text = soup.get_text(separator='\n', strip=True)[:15000]  # 15k chars max
        
        # Extraction des meta tags
        meta_info = {}
        for meta in soup.find_all('meta'):
            name = meta.get('name', meta.get('property', ''))
            content = meta.get('content', '')
            if name and content:
                meta_info[name] = content
        
        # Extraction des images
        images = []
        for img in soup.find_all('img')[:10]:
            src = img.get('src', img.get('data-src', ''))
            if src and 'product' in src.lower() or 'image' in src.lower():
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    domain = '/'.join(url.split('/')[:3])
                    src = domain + src
                images.append(src)
        
        # Extraction des données structurées (JSON-LD)
        json_ld_data = []
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                json_ld_data.append(data)
            except:
                pass
        
        # Prompt ultra-détaillé pour l'IA
        prompt = f"""Tu analyses une PAGE PRODUIT e-commerce. Extrais TOUTES les informations avec une précision maximale.

URL: {url}

MÉTADONNÉES:
{json.dumps(meta_info, indent=2, ensure_ascii=False)[:1000]}

DONNÉES STRUCTURÉES (JSON-LD):
{json.dumps(json_ld_data, indent=2, ensure_ascii=False)[:2000]}

CONTENU DE LA PAGE:
{body_text}

IMAGES DÉTECTÉES:
{json.dumps(images[:5], indent=2)}

MISSION CRITIQUE:
Extrais un objet JSON avec TOUTES ces informations (mets null si absent):

{{
  "nom": "Nom complet et exact du produit",
  "marque": "Marque du produit",
  "prix": "Prix en format XX.XX (euros)",
  "prix_barre": "Prix barré/avant réduction si existe",
  "reduction": "Pourcentage ou montant de réduction",
  "ean": "Code EAN-13 ou GTIN",
  "reference": "Référence produit/SKU",
  "description": "Description courte (max 300 chars)",
  "description_longue": "Description complète (max 800 chars)",
  "ingredients": "Liste des ingrédients si produit cosmétique/alimentaire",
  "contenance": "Volume/poids (ex: 50ml, 100g)",
  "image_url": "URL de l'image principale",
  "images_supplementaires": ["url1", "url2"],
  "disponibilite": "en_stock / rupture / sur_commande",
  "categorie": "Catégorie du produit",
  "notation": "Note moyenne (ex: 4.5)",
  "nombre_avis": "Nombre d'avis clients",
  "caracteristiques": {{"key": "value"}},
  "product_url": "{url}"
}}

RÈGLES STRICTES:
1. Retourne UNIQUEMENT le JSON, rien d'autre
2. Cherche l'EAN dans: meta tags, data attributes, JSON-LD, texte (format: 13 chiffres)
3. Prix: extrais même si format bizarre ("19€99" → "19.99")
4. Description: prends la plus complète
5. Si plusieurs prix, prends le prix actuel/TTC
6. Sois exhaustif, cherche partout

JSON:"""

        result = self.call_ai(prompt, max_tokens=4000, temperature=0.05)
        
        if result:
            try:
                result = result.strip()
                if "```json" in result:
                    result = result.split("```json")[1].split("```")[0]
                elif "```" in result:
                    result = result.split("```")[1].split("```")[0]
                
                # Cherche le JSON object
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    result = json_match.group(0)
                
                product = json.loads(result)
                return product
            except Exception as e:
                st.warning(f"⚠️ Erreur parsing produit {url}: {str(e)}")
                return None
        
        return None
    
    def scrape_product(self, url, index, total):
        """Scrape un produit individuel"""
        try:
            html = self.fetch_page(url)
            if html:
                product = self.ai_extract_product_details(html, url)
                if product:
                    return product
        except Exception as e:
            st.warning(f"⚠️ Erreur produit {index}/{total}: {str(e)}")
        return None
    
    def scrape_all_products(self, listing_url, max_workers=5):
        """Scrape TOUS les produits en parallèle"""
        # Étape 1: Récupérer la page de listing
        st.info("📋 Étape 1: Analyse de la page de listing...")
        html = self.fetch_page(listing_url)
        
        if not html:
            st.error("❌ Impossible de récupérer la page")
            return []
        
        # Étape 2: L'IA détecte toutes les URLs produits
        st.info("🔍 Étape 2: L'IA détecte toutes les URLs de produits...")
        product_urls = self.ai_detect_product_urls(html, listing_url)
        
        if not product_urls:
            st.error("❌ Aucune URL de produit détectée")
            return []
        
        st.success(f"✅ {len(product_urls)} URLs de produits détectées !")
        
        with st.expander("🔗 Voir les URLs détectées"):
            st.write(product_urls)
        
        # Étape 3: Scrape chaque produit en parallèle
        st.info(f"🤖 Étape 3: Extraction intelligente de {len(product_urls)} produits...")
        
        products = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Scraping parallèle pour aller plus vite
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.scrape_product, url, i+1, len(product_urls)): i 
                for i, url in enumerate(product_urls)
            }
            
            completed = 0
            for future in as_completed(futures):
                result = future.result()
                if result:
                    products.append(result)
                
                completed += 1
                progress = completed / len(product_urls)
                progress_bar.progress(progress)
                status_text.text(f"⏳ {completed}/{len(product_urls)} produits traités ({len(products)} extraits avec succès)")
                
                # Petite pause pour éviter de surcharger le serveur
                time.sleep(0.3)
        
        progress_bar.empty()
        status_text.empty()
        
        return products

# --- INTERFACE ---
st.title("🤖 Super Scraper AI - Intelligence Maximale")
st.markdown("""
### Le scraper le plus intelligent du marché
- 🎯 Détecte **TOUS** les produits automatiquement
- 🔍 Visite **chaque page produit** pour extraire les détails complets
- 🧠 L'IA trouve l'EAN, la description, les ingrédients, tout !
- ⚡ Scraping parallèle ultra-rapide
- 🚫 **Aucune limite** - scrape jusqu'au bout
""")

if GROQ_API_KEY:
    st.success("✅ IA Groq activée - Prêt pour l'extraction maximale")

url = st.text_input(
    "🔗 URL de la page de listing / catégorie",
    placeholder="https://www.exemple.com/categorie/produits",
    help="Entrez l'URL d'une page qui liste plusieurs produits"
)

col1, col2 = st.columns([3, 1])
with col1:
    start_btn = st.button("🚀 LANCER LE SUPER SCRAPING", type="primary", use_container_width=True)
with col2:
    max_workers = st.slider("Threads", 1, 10, 5, help="Nombre de produits scrapés en parallèle")

if start_btn:
    if not url:
        st.warning("⚠️ Entrez une URL")
    else:
        scraper = IntelligentScraper()
        
        start_time = time.time()
        
        with st.status("🔄 Scraping intelligent en cours...", expanded=True) as status:
            products = scraper.scrape_all_products(url, max_workers=max_workers)
            
            elapsed = time.time() - start_time
            
            if products:
                status.update(label=f"✅ {len(products)} produits extraits en {elapsed:.1f}s", state="complete")
                
                st.balloons()
                st.success(f"### 🎉 {len(products)} produits extraits avec TOUS les détails !")
                
                # Création DataFrame
                df = pd.DataFrame(products)
                
                # Affichage
                st.dataframe(df, use_container_width=True, height=600)
                
                # Statistiques détaillées
                st.markdown("### 📊 Statistiques d'extraction")
                
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric("📦 Produits", len(products))
                with col2:
                    nb_ean = df['ean'].notna().sum() if 'ean' in df.columns else 0
                    st.metric("🔢 EAN trouvés", f"{nb_ean} ({nb_ean*100//len(products)}%)")
                with col3:
                    nb_desc = df['description'].notna().sum() if 'description' in df.columns else 0
                    st.metric("📝 Descriptions", f"{nb_desc} ({nb_desc*100//len(products)}%)")
                with col4:
                    nb_img = df['image_url'].notna().sum() if 'image_url' in df.columns else 0
                    st.metric("🖼️ Images", f"{nb_img} ({nb_img*100//len(products)}%)")
                with col5:
                    st.metric("⏱️ Temps", f"{elapsed:.1f}s")
                
                # Colonnes disponibles
                with st.expander("📋 Colonnes disponibles dans le dataset"):
                    st.write(list(df.columns))
                
                # Export CSV
                csv = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(
                    "📥 Télécharger le CSV COMPLET",
                    csv,
                    f"scraping_complet_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                    "text/csv",
                    use_container_width=True
                )
                
                # Export JSON
                json_data = df.to_json(orient='records', force_ascii=False, indent=2)
                st.download_button(
                    "📥 Télécharger le JSON",
                    json_data,
                    f"scraping_complet_{time.strftime('%Y%m%d_%H%M%S')}.json",
                    "application/json",
                    use_container_width=True
                )
                
            else:
                status.update(label="❌ Aucun produit extrait", state="error")
                st.error("Aucun produit n'a pu être extrait. Vérifiez l'URL ou essayez un autre site.")

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    🧠 <b>Powered by Groq AI</b> - Scraping intelligent sans limite<br>
    💡 Plus de threads = plus rapide, mais attention à ne pas surcharger le serveur cible
</div>
""", unsafe_allow_html=True)
