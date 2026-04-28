import streamlit as st
import requests
import concurrent.futures
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import time
import pandas as pd

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="AcademiGraph Pro | Top Impact Edition", 
    layout="wide", 
    page_icon="🏆"
)

# --- DISEÑO DE INTERFAZ ---
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #2e7bcf; color: white; border: none; font-weight: bold; }
    .stDownloadButton>button { width: 100%; border-radius: 8px; background-color: #1c83e1; color: white; }
    .stProgress > div > div > div > div { background-color: #4CAF50; }
    </style>
    """, unsafe_allow_html=True)

# --- 1. MOTORES DE BÚSQUEDA (ORDENADOS POR CITAS) ---

def buscar_federado_top(materia, limite, email):
    resultados = []
    
    def buscar_oa():
        try:
            # Filtro: sort=cited_by_count:desc (Los más citados primero)
            res = requests.get("https://api.openalex.org/works", 
                               params={
                                   "search": materia, 
                                   "per-page": limite, 
                                   "mailto": email,
                                   "sort": "cited_by_count:desc"
                               }, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("results", []):
                    doi_url = item.get("doi")
                    resultados.append({
                        "Fuente": "OpenAlex (Top)", 
                        "Título": item.get("title"),
                        "Autor": item.get("authorships", [{}])[0].get("author", {}).get("display_name", "N/A"),
                        "DOI": doi_url.replace("https://doi.org/", "") if doi_url else None,
                        "Citas_Aprox": item.get("cited_by_count", 0)
                    })
        except: pass

    def buscar_cr():
        try:
            # Filtro: sort=is-referenced-by-count (Orden por impacto en Crossref)
            res = requests.get("https://api.crossref.org/works", 
                               params={
                                   "query": materia, 
                                   "rows": limite, 
                                   "mailto": email,
                                   "sort": "is-referenced-by-count",
                                   "order": "desc"
                               }, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("message", {}).get("items", []):
                    autores = item.get("author", [])
                    autor = autores[0].get('family') if autores else "N/A"
                    resultados.append({
                        "Fuente": "Crossref (Top)", 
                        "Título": item.get("title", [""])[0],
                        "Autor": autor, 
                        "DOI": item.get("DOI"),
                        "Citas_Aprox": item.get("is-referenced-by-count", 0)
                    })
        except: pass

    def buscar_uco():
        try:
            # UCO Mezquita: Usamos relevancia (combina citas y términos)
            url = "https://mezquita.uco.es/primaws/rest/pub/pnxs"
            params = {"q": f"any,contains,{materia}", "limit": limite, "vid": "34CBUA_UCO:VU1", "tab": "Everything", "scope": "MyInst_and_CI", "inst": "34CBUA_UCO"}
            res = requests.get(url, params=params, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("docs", []):
                    pnx = item.get("pnx", {})
                    disp = pnx.get("display", {})
                    doi = pnx.get("addata", {}).get("doi", [None])[0]
                    resultados.append({
                        "Fuente": "UCO", 
                        "Título": disp.get("title", [""])[0],
                        "Autor": disp.get("creator", ["N/A"])[0], 
                        "DOI": doi,
                        "Citas_Aprox": "N/A"
                    })
        except: pass

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(buscar_oa)
        executor.submit(buscar_cr)
        executor.submit(buscar_uco)
        
    return resultados

# --- 2. MOTOR DE RED BIDIRECCIONAL ---

def obtener_red_completa(doi, titulo, limite_red=5):
    refs, cits = [], []
    try:
        url_id = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}" if doi else f"https://api.semanticscholar.org/graph/v1/paper/search?query={titulo}&limit=1"
        res_id = requests.get(url_id, timeout=10)
        
        if res_id.status_code == 200:
            data = res_id.json()
            p_id = data.get("paperId") if doi else data.get("data", [{}])[0].get("paperId")
            
            if p_id:
                # Referencias (Pasado)
                r_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/references", 
                                     params={"limit": limite_red, "fields": "title"}, timeout=10)
                if r_res.status_code == 200:
                    refs = [i['citedPaper']['title'] for i in r_res.json().get('data', []) if i.get('citedPaper')]
                
                time.sleep(0.6) 

                # Citas (Futuro)
                c_res = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/{p_id}/citations", 
                                     params={"limit": limite_red, "fields": "title"}, timeout=10)
                if c_res.status_code == 200:
                    cits = [i['citingPaper']['title'] for i in c_res.json().get('data', []) if i.get('citingPaper')]
    except: pass
    return refs, cits

# --- 3. INTERFAZ ---

st.title("🎓 AcademiGraph Pro: Impact Search")
st.markdown("Esta versión prioriza los **artículos más influyentes** (más citados) de cada base de datos.")

with st.sidebar:
    st.header("⚙️ Filtros de Calidad")
    user_email = st.text_input("Email (Polite Pool)", "investigador@institucion.edu")
    n_results = st.slider("Top artículos por buscador", 1, 10, 5)
    st.divider()
    st.info("💡 Al buscar los más citados, las conexiones entre artículos suelen ser más ricas y densas.")

query = st.text_input("Investigar materia:", placeholder="Ej: Quantum Computing")

if st.button("🚀 Iniciar Investigación de Alto Impacto"):
    if query:
        with st.status("Identificando artículos núcleo (Core Papers)...", expanded=True) as s:
            data_base = buscar_federado_top(query, n_results, user_email)
            s.write(f"✅ Se han seleccionado los {len(data_base)} artículos más influyentes encontrados.")
            
            s.write("Mapeando el ecosistema de citación...")
            grafo = nx.DiGraph()
            progreso = st.progress(0)
            
            for i, art in enumerate(data_base):
                refs, cits = obtener_red_completa(art['DOI'], art['Título'])
                
                # Nodo central (Impacto)
                grafo.add_node(art['Título'], color='#4CAF50', size=35, title=f"Citas: {art['Citas_Aprox']}")
                
                for r in refs:
                    grafo.add_node(r, color='#FF5722', size=15)
                    grafo.add_edge(art['Título'], r, color='#FF5722')
                
                for c in cits:
                    grafo.add_node(c, color='#2196F3', size=15)
                    grafo.add_edge(c, art['Título'], color='#2196F3')
                
                progreso.progress((i + 1) / len(data_base))
                time.sleep(1)

            s.update(label="¡Mapa de impacto completado!", state="complete")

        col_map, col_data = st.columns([2, 1])
        
        with col_map:
            st.markdown("### 🕸️ Red de Influencia (Top Papers)")
            net = Network(height="700px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.repulsion(node_distance=250)
            components.html(net.generate_html(), height=750)

        with col_data:
            st.markdown("### 📊 Ranking de Resultados")
            df = pd.DataFrame(data_base)
            st.dataframe(df.sort_values(by="Citas_Aprox", ascending=False) if "Citas_Aprox" in df else df, use_container_width=True)
            
            st.download_button("📥 Descargar Reporte Impacto", df.to_csv(index=False).encode('utf-8'), "reporte_impacto.csv", "text/csv")
    else:
        st.warning("Introduce un término de búsqueda.")
