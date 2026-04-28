import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import time
import pandas as pd
import unicodedata
import re

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="AcademiGraph Pro | High Recovery", layout="wide", page_icon="🚀")

def normalizar_simple(texto):
    if not texto: return ""
    return " ".join(texto.lower().split())

# --- ENRIQUECIMIENTO ---
def enriquecer_citas_flexible(articulo):
    if articulo.get("Citas") and articulo["Citas"] > 0:
        return articulo
    try:
        doi = articulo.get("DOI")
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={articulo['Título']}&limit=1&fields=citationCount"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            articulo["Citas"] = data.get("citationCount") if doi else data.get("data", [{}])[0].get("citationCount", 0)
    except: pass
    return articulo

# --- MOTORES (RECUPERANDO CORE Y PUBMED) ---
def buscar_federado_recuperacion(materia, limite, email, perfil, campo):
    resultados = []
    
    def buscar_oa():
        try:
            p = {"per-page": limite, "mailto": email, "sort": "cited_by_count:desc"}
            if campo == "ORCID": p["filter"] = f"author.orcid:https://orcid.org/{materia}"
            elif campo == "Título": p["filter"] = f"title.search:{materia}"
            elif campo == "Autor (Nombre)": p["filter"] = f"authorships.author.display_name.search:{materia}"
            else: p["search"] = f"{materia} (law OR economics OR business)" if perfil == "Derecho/Economía" else materia
            
            res = requests.get("https://api.openalex.org/works", params=p, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({
                        "Fuente": "Dimensions/OA", "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": item.get("doi", "").replace("https://doi.org/", ""), "Citas": int(item.get("cited_by_count", 0))
                    })
        except: pass

    def buscar_cr():
        try:
            p = {"rows": limite, "sort": "is-referenced-by-count", "order": "desc"}
            if campo == "ORCID": p["filter"] = f"orcid:{materia}"
            elif campo == "Título": p["query.title"] = materia
            elif campo == "Autor (Nombre)": p["query.author"] = materia
            else: p["query"] = materia
            res = requests.get("https://api.crossref.org/works", params=p, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    resultados.append({
                        "Fuente": "Crossref", "Título": item.get("title", [""])[0],
                        "Autor": item.get("author", [{}])[0].get("family", "N/A") if item.get("author") else "N/A",
                        "DOI": item.get("DOI"), "Citas": int(item.get("is-referenced-by-count", 0))
                    })
        except: pass

    def buscar_core():
        try:
            q = f"authors:({materia})" if campo in ["Autor (Nombre)", "ORCID"] else f"title:({materia})" if campo == "Título" else materia
            res = requests.get("https://api.core.ac.uk/v3/search/works", params={"q": q, "limit": limite}, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    resultados.append({"Fuente": "CORE", "Título": item.get("title"), "Autor": "N/A", "DOI": item.get("doi"), "Citas": 0})
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_cr)
        executor.submit(buscar_core)
        if perfil == "General":
            # Aquí iría la función de PubMed similar a las anteriores
            pass
            
    return resultados

# --- RED ---
@st.cache_data(ttl=3600)
def obtener_red(doi, titulo):
    refs, cits = [], []
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            pid = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            if pid:
                r = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{pid}/references", params={"limit": 5, "fields": "title"}).json()
                refs = [i['citedPaper']['title'] for i in r.get('data', []) if i.get('citedPaper')]
                c = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{pid}/citations", params={"limit": 5, "fields": "title"}).json()
                cits = [i['citingPaper']['title'] for i in c.get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- INTERFAZ ---
st.title("🚀 AcademiGraph Pro: Recuperación de Volumen")

with st.sidebar:
    campo = st.selectbox("Buscar por:", ["Palabras Clave", "Título", "Autor (Nombre)", "ORCID"])
    perfil = st.selectbox("Perfil:", ["General", "Derecho/Economía"])
    n_res = st.slider("Resultados por motor", 5, 25, 15)

query = st.text_input(f"Introduce {campo}:")

if st.button("🚀 Investigar"):
    if query:
        with st.status("Buscando...") as s:
            data_raw = buscar_federado_recuperacion(query, n_res, "test@test.com", perfil, campo)
            with concurrent.futures.ThreadPoolExecutor() as executor:
                data_base = list(executor.map(enriquecer_citas_flexible, data_raw))
            
            grafo = nx.DiGraph()
            for art in data_base:
                r, c = obtener_red(art['DOI'], art['Título'])
                grafo.add_node(art['Título'], color='#4CAF50', size=25)
                for x in r: grafo.add_edge(art['Título'], x)
                for x in c: grafo.add_edge(x, art['Título'])
                time.sleep(0.5)
            s.update(label="Listo", state="complete")
            
        col1, col2 = st.columns([2, 1])
        with col1:
            net = Network(height="600px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            components.html(net.generate_html(), height=650)
        with col2:
            st.dataframe(pd.DataFrame(data_base))
