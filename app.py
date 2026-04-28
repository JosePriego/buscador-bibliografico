# --- (Mantén las funciones de búsqueda y enriquecimiento anteriores) ---

# ... [Código previo de motores de búsqueda] ...

if st.button("🚀 Iniciar Gran Búsqueda"):
    if query:
        with st.status("Consultando repositorios globales...", expanded=True) as s:
            data_raw = buscar_federado_global(query, n_results, user_email, perfil, campo_busqueda)
            data_raw = [d for d in data_raw if d['Título']]
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                data_base = list(executor.map(enriquecer_citas, data_raw))
            
            grafo = nx.DiGraph()
            
            for i, art in enumerate(data_base):
                r_list, c_list = obtener_red_cached(art['DOI'], art['Título'])
                # NODO PRINCIPAL (Verde)
                grafo.add_node(art['Título'], color='#4CAF50', size=30, title="Artículo encontrado")
                
                # REFERENCIAS (Rojo) - Lo que el autor cita
                for r in r_list:
                    grafo.add_node(r, color='#FF5722', size=15, title="Referencia bibliográfica (citada por el autor)")
                    grafo.add_edge(art['Título'], r, color='#FF5722')
                
                # CITAS (Azul) - Quién cita al autor
                for c in c_list:
                    grafo.add_node(c, color='#2196F3', size=15, title="Cita recibida (quién cita a este autor)")
                    grafo.add_edge(c, art['Título'], color='#2196F3')
                
                time.sleep(1.1)
            s.update(label="¡Procesamiento completo!", state="complete")

        # --- NUEVA SECCIÓN DE LEYENDA Y MAPA ---
        col_m, col_d = st.columns([2, 1])
        
        with col_m:
            # LEYENDA VISUAL
            st.markdown("""
                <div style="display: flex; gap: 20px; margin-bottom: 10px; justify-content: center; background: #1e2130; padding: 10px; border-radius: 10px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div style="width: 15px; height: 15px; background-color: #4CAF50; border-radius: 50%;"></div>
                        <span style="font-size: 14px;">Artículo Principal</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div style="width: 15px; height: 15px; background-color: #FF5722; border-radius: 50%;"></div>
                        <span style="font-size: 14px;">Referencia (Pasado)</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div style="width: 15px; height: 15px; background-color: #2196F3; border-radius: 50%;"></div>
                        <span style="font-size: 14px;">Cita (Futuro)</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # GENERACIÓN DEL GRÁFICO
            net = Network(height="700px", width="100%", bgcolor="#0e1117", font_color="white", directed=True)
            net.from_nx(grafo)
            net.toggle_physics(True)
            net.repulsion(node_distance=180)
            components.html(net.generate_html(), height=750)

        with col_d:
            st.markdown("### 📊 Ranking de Impacto")
            df = pd.DataFrame(data_base)
            if not df.empty:
                df["Citas"] = pd.to_numeric(df["Citas"], errors='coerce').fillna(0).astype(int)
                st.dataframe(df.sort_values(by="Citas", ascending=False), use_container_width=True)
