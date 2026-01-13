import streamlit as st
import os
import json
import asyncio
import pandas as pd
import google.generativeai as genai
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests

# --- CONFIGURATION ---
st.set_page_config(page_title="Smart Scraper AI - Gemini", page_icon="🛒", layout="wide")

# Initialisation de Gemini
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    st.error("⚠️ GEMINI_API_KEY manquante dans les Secrets de Streamlit.")

class SmartScraper:
    async def fetch_page(self, url):
        async with async_playwright() as p:
            # On utilise le navigateur installé par Streamlit
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(2)
                content = await page.content()
                await browser.close()
                return content
            except Exception as e:
                await browser.close()
                return None

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        for s in soup(["script", "style", "nav", "footer", "header", "svg"]):
            s.decompose()
        return soup.prettify()[:30000]

    async def extract_with_gemini(self, html_content):
        prompt = f"Analyse ce HTML et extrais les produits en JSON (Nom, Prix, Marque, EAN, Image_URL, Product_URL). HTML: {html_content}"
        try:
            response = model.generate_content(prompt)
            res_text = response.text
            if "```json" in res_text:
                res_text = res_text.split("```json")[1].split("```")[0]
            return json.loads(res_text)
        except:
            return []

# --- UI ---
st.title("🛒 Smart Scraper AI (Gemini)")

url_input = st.text_input("URL du site")

if st.button("Lancer l'extraction"):
    if api_key and url_input:
        scraper = SmartScraper()
        with st.spinner("Analyse en cours..."):
            html = asyncio.run(scraper.fetch_page(url_input))
            if html:
                products = asyncio.run(scraper.extract_with_gemini(scraper.clean_html(html)))
                if products:
                    df = pd.DataFrame(products)
                    st.dataframe(df)
                    st.download_button("Télécharger CSV", df.to_csv(index=False), "data.csv")
                else:
                    st.warning("Aucun produit trouvé.")
            else:
                st.error("Erreur de chargement de la page.")
