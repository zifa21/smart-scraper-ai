import streamlit as st
import os
import json
import pandas as pd
import google.generativeai as genai
from bs4 import BeautifulSoup
import requests
import time
import re

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Scraper AI - Gemini", page_icon="🛒", layout="wide")

# --- INITIALISATION GEMINI ---
api_key = st.secrets.get("GEMINI_API_KEY") if hasattr(st, 'secrets') else os.getenv("GEMINI_API_KEY")

if api_key:
    genai.configure(api_key=api_key)
    # Utilisation de gemini-2.0-flash-exp (gratuit et performant)
    model = genai.GenerativeModel('gemini-2.0-flash-exp')
else:
    st.error("⚠️ GEMINI_API_KEY manquante. Ajoutez-la dans les Secrets de Streamlit ou en variable d'environnement.")
    st.stop()

class SmartScraper:
    def fetch_page(self, url):
        """Récupère le contenu HTML d'une page"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        try:
            session = requests.Session()
            response = session.get(url, headers=headers, timeout=30, allow_redirects=True)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            st.error(f"❌ Erreur de connexion : {str(e)}")
            return None

    def clean_html(self, html, url):
        """Nettoie et simplifie le HTML pour l'analyse"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Suppression des éléments inutiles
        for tag in soup(["script", "style", "nav", "footer", "header", "svg", "path", "iframe", "aside", "noscript"]):
            tag.decompose()
        
        # Extraction du domaine pour les URLs relatives
        domain = '/'.join(url.split('/')[:3])
        
        # On cherche les conteneurs de produits (patterns courants)
        product_containers = []
        
        # Patterns communs pour les produits
        product_selectors = [
            {'class': re.compile(r'product', re.I)},
            {'class': re.compile(r'item', re.I)},
            {'data-product-id': True},
            {'itemtype': re.compile(r'Product', re.I)}
        ]
        
        for selector in product_selectors:
            product_containers.extend(soup.find_all(['div', 'article', 'li'], selector))
        
        # Si pas de conteneurs trouvés, on prend tout
        if not product_containers:
            product_containers = [soup.body] if soup.body else [soup]
        
        # Construction du HTML simplifié
        simplified_parts = []
        for container in product_containers[:50]:  # Limite à 50 produits max
            text_content = container.get_text(separator=' ', strip=True)
            
            # Extraction des images
            images = [img.get('src', img.get('data-src', '')) for img in container.find_all('img')]
            images = [img if img.startswith('http') else domain + img for img in images if img]
            
            # Extraction des liens
            links = [a.get('href', '') for a in container.find_all('a', href=True)]
            links = [link if link.startswith('http') else domain + link for link in links]
            
            # Extraction des attributs intéressants
            attributes = []
            for attr in ['data-ean', 'data-gtin', 'data-product-id', 'data-price', 'data-name']:
                if container.get(attr):
                    attributes.append(f"{attr}='{container.get(attr)}'")
            
            simplified_parts.append({
                'text': text_content[:500],  # Limite le texte
                'images': images[:3],  # Max 3 images par produit
                'links': links[:3],  # Max 3 liens par produit
                'attributes': ' '.join(attributes)
            })
        
        return simplified_parts

    def extract_with_gemini(self, content_parts, url):
        """Utilise Gemini pour extraire les données produits"""
        
        # Formatage du contenu pour Gemini
        formatted_content = "PRODUITS DÉTECTÉS:\n\n"
        for i, part in enumerate(content_parts[:20], 1):  # Max 20 produits pour ne pas dépasser les limites
            formatted_content += f"--- PRODUIT {i} ---\n"
            formatted_content += f"Texte: {part['text']}\n"
            if part['attributes']:
                formatted_content += f"Attributs: {part['attributes']}\n"
            if part['images']:
                formatted_content += f"Images: {', '.join(part['images'])}\n"
            if part['links']:
                formatted_content += f"Liens: {', '.join(part['links'])}\n"
            formatted_content += "\n"
        
        prompt = f"""Tu es un expert en extraction de données e-commerce.

Analyse le contenu suivant provenant de {url} et extrais TOUS les produits détectés.

Pour chaque produit, crée un objet JSON avec ces champs :
- "nom": nom du produit (string)
- "prix": prix en euros (string, ex: "19.99")
- "marque": marque si disponible (string ou null)
- "ean": code EAN/GTIN si disponible (string ou null)
- "image_url": URL de l'image principale (string ou null)
- "product_url": URL de la page produit (string ou null)

RÈGLES IMPORTANTES:
1. Retourne UNIQUEMENT un array JSON valide, sans texte avant ou après
2. Si une info n'est pas disponible, mets null
3. Pour les URLs relatives, ajoute le domaine {url.split('/')[0]}//{url.split('/')[2]}
4. Extrais le prix même s'il est dans le texte (ex: "19€99" → "19.99")
5. Ne crée qu'une entrée par produit unique

CONTENU À ANALYSER:
{formatted_content}

Réponds uniquement avec le JSON:"""

        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=8000,
                )
            )
            
            result_text = response.text.strip()
            
            # Nettoyage de la réponse
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            products = json.loads(result_text)
            
            # Validation que c'est bien une liste
            if not isinstance(products, list):
                st.warning("La réponse n'est pas une liste. Tentative de correction...")
                products = [products] if isinstance(products, dict) else []
            
            return products
            
        except json.JSONDecodeError as e:
            st.error(f"❌ Erreur de décodage JSON: {str(e)}")
            st.code(result_text[:500], language="text")
            return []
        except Exception as e:
            st.error(f"❌ Erreur Gemini: {str(e)}")
            return []

# --- INTERFACE ---
st.title("🛒 Smart Scraper AI - Gemini 2.0 Flash")
st.markdown("### Outil d'extraction automatique pour le Retail Arbitrage")

with st.expander("ℹ️ Comment utiliser cet outil"):
    st.markdown("""
    1. Entrez l'URL d'une page de listing produits (Lidl, Fnac, Carrefour, etc.)
    2. Cliquez sur "Lancer l'extraction"
    3. L'IA analysera la page et extraira les produits automatiquement
    4. Téléchargez les résultats en CSV
    
    **Note**: Certains sites utilisent des protections anti-scraping qui peuvent bloquer les requêtes.
    """)

url_input = st.text_input(
    "🔗 URL du site à analyser",
    placeholder="https://www.exemple.com/produits",
    help="Entrez l'URL complète de la page de listing"
)

col1, col2 = st.columns([1, 4])
with col1:
    extract_button = st.button("🚀 Lancer l'extraction", type="primary", use_container_width=True)

if extract_button:
    if not url_input:
        st.warning("⚠️ Veuillez entrer une URL.")
    elif not url_input.startswith('http'):
        st.warning("⚠️ L'URL doit commencer par http:// ou https://")
    else:
        scraper = SmartScraper()
        
        with st.status("🔄 Extraction en cours...", expanded=True) as status:
            # Étape 1: Récupération
            st.write("🌐 Connexion au site...")
            html = scraper.fetch_page(url_input)
            
            if not html:
                status.update(label="❌ Échec de la récupération", state="error")
                st.stop()
            
            st.write(f"✅ Page récupérée ({len(html)} caractères)")
            
            # Étape 2: Nettoyage
            st.write("🧹 Nettoyage et structuration du contenu...")
            content_parts = scraper.clean_html(html, url_input)
            st.write(f"✅ {len(content_parts)} sections de produits détectées")
            
            # Étape 3: Analyse IA
            st.write("🤖 Analyse intelligente avec Gemini...")
            products = scraper.extract_with_gemini(content_parts, url_input)
            
            if products and len(products) > 0:
                status.update(label=f"✅ Extraction terminée - {len(products)} produits trouvés", state="complete")
                
                # Affichage des résultats
                st.success(f"### 🎉 {len(products)} produits extraits avec succès!")
                
                df = pd.DataFrame(products)
                
                # Réorganisation des colonnes
                cols_order = ['nom', 'prix', 'marque', 'ean', 'product_url', 'image_url']
                cols_order = [col for col in cols_order if col in df.columns]
                df = df[cols_order]
                
                # Affichage du tableau
                st.dataframe(df, use_container_width=True, height=400)
                
                # Statistiques
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Produits", len(products))
                with col2:
                    nb_with_price = df['prix'].notna().sum() if 'prix' in df.columns else 0
                    st.metric("Avec prix", nb_with_price)
                with col3:
                    nb_with_ean = df['ean'].notna().sum() if 'ean' in df.columns else 0
                    st.metric("Avec EAN", nb_with_ean)
                
                # Téléchargement
                csv = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(
                    "📥 Télécharger le CSV",
                    csv,
                    f"arbitrage_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                    "text/csv",
                    use_container_width=True
                )
                
            else:
                status.update(label="⚠️ Aucun produit trouvé", state="error")
                st.warning("""
                Aucun produit n'a pu être extrait. Causes possibles:
                - Le site utilise du JavaScript pour charger les produits
                - La structure HTML n'est pas reconnue
                - Le site bloque les requêtes automatiques
                
                Essayez avec une autre page ou un autre site.
                """)

# Footer
st.markdown("---")
st.markdown("💡 **Astuce**: Pour de meilleurs résultats, utilisez des pages de listing/catégorie plutôt que des pages produit individuelles.")
