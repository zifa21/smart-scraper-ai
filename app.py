import streamlit as st
import os
import json
import pandas as pd
from bs4 import BeautifulSoup
import requests
import time
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Smart Scraper AI - Groq", page_icon="🛒", layout="wide")

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY") if hasattr(st, 'secrets') else os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error("⚠️ GROQ_API_KEY manquante")
    st.stop()

class SmartScraper:
    def __init__(self):
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
    
    def call_ai(self, prompt, max_tokens=8000):
        """Appelle Groq AI"""
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "Tu es un expert en extraction de données e-commerce. Tu extrais TOUS les produits sans exception. Réponds UNIQUEMENT en JSON valide."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens
        }
        
        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=90)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            st.error(f"❌ Erreur API: {str(e)}")
            return None
    
    def fetch_page(self, url):
        """Récupère la page web"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            st.error(f"❌ Erreur connexion: {str(e)}")
            return None

    def clean_html(self, html, url):
        """Nettoie le HTML et extrait TOUS les produits"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Supprime le bruit
        for tag in soup(["script", "style", "nav", "footer", "header", "svg", "path", "noscript"]):
            tag.decompose()
        
        domain = '/'.join(url.split('/')[:3])
        products = []
        seen_texts = set()
        
        # 🔍 STRATÉGIE 1: Cherche des patterns spécifiques de produits
        product_patterns = [
            ('div', {'class': re.compile(r'product|item|card|listing|article', re.I)}),
            ('article', {}),
            ('li', {'class': re.compile(r'product|item', re.I)}),
            ('div', {'data-product-id': True}),
            ('div', {'data-item-id': True}),
        ]
        
        containers = []
        for tag, attrs in product_patterns:
            containers.extend(soup.find_all(tag, attrs))
        
        # 🔍 STRATÉGIE 2: Si peu de résultats, cherche TOUS les divs/articles
        if len(containers) < 5:
            st.info("🔍 Recherche approfondie...")
            all_containers = soup.find_all(['div', 'article', 'section'])
            # Filtre ceux qui contiennent des images ET du texte (probablement des produits)
            for container in all_containers:
                has_image = container.find('img') is not None
                has_text = len(container.get_text(strip=True)) > 20
                has_link = container.find('a') is not None
                
                if has_image and has_text and has_link:
                    containers.append(container)
        
        st.write(f"🔎 {len(containers)} conteneurs détectés")
        
        # Extraction des données de chaque conteneur
        for container in containers[:100]:  # Maximum 100 produits
            text = container.get_text(separator=' ', strip=True)
            
            # Évite les doublons
            text_signature = text[:100]
            if text_signature in seen_texts or len(text) < 15:
                continue
            seen_texts.add(text_signature)
            
            # Extraction images
            images = []
            for img in container.find_all('img'):
                src = img.get('src', img.get('data-src', img.get('data-lazy-src', img.get('data-original', ''))))
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = domain + src
                    elif not src.startswith('http'):
                        src = domain + '/' + src
                    if 'placeholder' not in src.lower() and 'icon' not in src.lower():
                        images.append(src)
            
            # Extraction liens
            links = []
            for a in container.find_all('a', href=True):
                href = a.get('href')
                if href and href != '#':
                    if href.startswith('//'):
                        href = 'https:' + href
                    elif href.startswith('/'):
                        href = domain + href
                    elif not href.startswith('http'):
                        href = domain + '/' + href
                    links.append(href)
            
            # Extraction attributs intéressants
            attrs = {}
            for attr in ['data-product-id', 'data-ean', 'data-gtin', 'data-price', 'data-name']:
                val = container.get(attr)
                if val:
                    attrs[attr] = val
            
            products.append({
                'text': text[:800],  # Augmenté pour plus de contexte
                'images': images[:3],
                'links': links[:2],
                'attrs': attrs
            })
        
        return products

    def extract_products_batch(self, content_parts, url, batch_size=15):
        """Extraction par batch pour traiter plus de produits"""
        all_products = []
        total_batches = (len(content_parts) + batch_size - 1) // batch_size
        
        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(content_parts))
            batch = content_parts[start_idx:end_idx]
            
            st.write(f"📦 Traitement batch {batch_idx + 1}/{total_batches} ({len(batch)} produits)")
            
            formatted = f"LISTE DE PRODUITS E-COMMERCE (Batch {batch_idx + 1}/{total_batches}):\n\n"
            for i, part in enumerate(batch, start_idx + 1):
                formatted += f"=== PRODUIT {i} ===\n"
                formatted += f"Texte: {part['text']}\n"
                if part['attrs']:
                    formatted += f"Attributs: {json.dumps(part['attrs'])}\n"
                if part['images']:
                    formatted += f"Image: {part['images'][0]}\n"
                if part['links']:
                    formatted += f"URL: {part['links'][0]}\n"
                formatted += "\n"
            
            prompt = f"""Tu analyses une page e-commerce. Extrais TOUS les produits de ce batch.

Pour CHAQUE produit détecté, crée un objet JSON avec:
- "nom": nom complet du produit (obligatoire)
- "prix": prix en format "XX.XX" (string, ou null)
- "marque": marque si trouvée (string ou null)
- "ean": code EAN/GTIN si présent (string ou null)
- "image_url": URL complète de l'image (string ou null)
- "product_url": URL complète du produit (string ou null)

RÈGLES CRITIQUES:
1. Retourne UNIQUEMENT un array JSON pur : [{...}, {...}, ...]
2. N'oublie AUCUN produit de la liste
3. Si info manquante, mets null
4. Prix: extrais même format "XX€XX" → "XX.XX"
5. Un seul produit = une seule entrée

CONTENU:
{formatted}

JSON:"""

            result = self.call_ai(prompt)
            if result:
                try:
                    # Nettoie la réponse
                    result = result.strip()
                    if "```json" in result:
                        result = result.split("```json")[1].split("```")[0]
                    elif "```" in result:
                        result = result.split("```")[1].split("```")[0]
                    
                    # Cherche le JSON array
                    json_match = re.search(r'\[\s*\{.*?\}\s*\]', result, re.DOTALL)
                    if json_match:
                        result = json_match.group(0)
                    
                    products = json.loads(result)
                    if isinstance(products, list):
                        all_products.extend(products)
                        st.success(f"✅ {len(products)} produits extraits de ce batch")
                    else:
                        all_products.append(products)
                except json.JSONDecodeError as e:
                    st.warning(f"⚠️ Erreur parsing batch {batch_idx + 1}: {str(e)}")
                    with st.expander(f"Voir réponse brute batch {batch_idx + 1}"):
                        st.code(result[:500])
            
            # Petite pause entre les batches
            if batch_idx < total_batches - 1:
                time.sleep(0.5)
        
        return all_products

# --- INTERFACE ---
st.title("🛒 Smart Scraper AI - Groq (Extraction Complète)")
st.markdown("### Extraction gratuite et illimitée - Version optimisée")

if GROQ_API_KEY:
    st.success("✅ API Groq connectée")

url = st.text_input(
    "🔗 URL du site", 
    placeholder="https://www.exemple.com/produits",
    value="https://www.pharma-gdd.com/fr/promotions"  # URL par défaut pour test
)

col1, col2 = st.columns([3, 1])
with col1:
    extract_btn = st.button("🚀 Extraire TOUS les produits", type="primary", use_container_width=True)
with col2:
    batch_size = st.number_input("Produits/batch", 10, 30, 15, help="Nombre de produits analysés par requête IA")

if extract_btn:
    if not url:
        st.warning("⚠️ Entrez une URL")
    else:
        scraper = SmartScraper()
        
        with st.status("🔄 Extraction en cours...", expanded=True) as status:
            # Étape 1: Récupération
            st.write("🌐 Connexion au site...")
            html = scraper.fetch_page(url)
            
            if not html:
                status.update(label="❌ Échec", state="error")
                st.stop()
            
            st.write(f"✅ Page récupérée ({len(html):,} caractères)")
            
            # Étape 2: Extraction HTML
            st.write("🔍 Détection des produits dans le HTML...")
            parts = scraper.clean_html(html, url)
            
            if not parts:
                status.update(label="⚠️ Aucun produit détecté", state="error")
                st.warning("La page ne contient pas de structure produit détectable.")
                st.stop()
            
            st.write(f"✅ {len(parts)} zones produits détectées")
            
            # Étape 3: Extraction IA par batch
            st.write("🤖 Analyse intelligente par Groq...")
            products = scraper.extract_products_batch(parts, url, batch_size=batch_size)
            
            if products:
                status.update(label=f"✅ {len(products)} produits extraits avec succès !", state="complete")
                
                st.balloons()
                st.success(f"### 🎉 {len(products)} produits trouvés !")
                
                # Création DataFrame
                df = pd.DataFrame(products)
                
                # Réorganisation colonnes
                cols_order = ['nom', 'prix', 'marque', 'ean', 'product_url', 'image_url']
                cols_order = [col for col in cols_order if col in df.columns]
                df = df[cols_order]
                
                # Affichage
                st.dataframe(df, use_container_width=True, height=500)
                
                # Statistiques
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("📦 Total produits", len(products))
                with col2:
                    nb_price = df['prix'].notna().sum() if 'prix' in df.columns else 0
                    st.metric("💰 Avec prix", f"{nb_price} ({nb_price*100//len(products)}%)")
                with col3:
                    nb_ean = df['ean'].notna().sum() if 'ean' in df.columns else 0
                    st.metric("🔢 Avec EAN", f"{nb_ean} ({nb_ean*100//len(products) if len(products) > 0 else 0}%)")
                with col4:
                    nb_img = df['image_url'].notna().sum() if 'image_url' in df.columns else 0
                    st.metric("🖼️ Avec image", f"{nb_img} ({nb_img*100//len(products)}%)")
                
                # Export CSV
                csv = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(
                    "📥 Télécharger le CSV complet",
                    csv,
                    f"extraction_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                    "text/csv",
                    use_container_width=True
                )
                
            else:
                status.update(label="⚠️ Aucun produit extrait", state="error")
                st.warning("L'IA n'a pas réussi à extraire les produits. Le site utilise peut-être une structure inhabituelle.")

st.markdown("---")
st.caption("💡 Propulsé par Groq - Extraction par batch pour maximiser les résultats")
