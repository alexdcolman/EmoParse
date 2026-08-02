# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.network_cmd
#
#  Subcomando `emoparse network`: análisis de redes sobre un run de posts.
#
#  Flujo:
#  1) Lee posts, tecno_entidades y emociones de la DB del run.
#  2) Construye las aristas de los grafos pedidos (--graphs). El grafo
#     `follow` no se construye: se lee ya persistido por `emoparse follows`.
#  3) Calcula métricas por nodo, comunidades (Louvain, seed fija) y, con
#     --cliques, las cliques de vínculos recíprocos.
#  4) Persiste aristas y métricas en la DB (idempotente por grafo).
#  5) Acoplamiento emocional: perfil fórico por comunidad, matriz de
#     transición en hilos y, con --flujo, cómo circula la emoción entre
#     comunidades (contagio por tipo y transición intra vs inter).
#  6) Con --similitud, agrupa los simulacros emocionales por parecido entre
#     sus componentes (agrupamiento narrativo) y persiste el resultado como
#     un grafo más.
#  7) Con --semantico, agrupa los posts por contenido (extra `embeddings`).
#  8) Con --export-dir, exporta GEXF + CSVs por grafo (abren en Gephi) y las
#     tablas de cada análisis.
#
#  Sin LLM. Requiere el extra `network` (networkx); --semantico requiere
#  además el extra `embeddings`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from emoparse.network import (
    GRAFO_FOLLOW,
    GRAFOS,
    GRAFOS_AUTOR,
    build_edges,
    community_emotion_profile,
    compute_node_metrics,
    contagion_lift,
    detect_cliques,
    detect_communities,
    flujo_entre_comunidades,
    foria_by_post,
    foria_transition_matrix,
    foria_transition_by_scope,
    tipos_por_post,
    to_graph,
)
from emoparse.network import simulacro_similarity as sim
from emoparse.network.emotion_coupling import FORIAS
from emoparse.network.export import export_graph, export_table
from emoparse.network.metrics import NetworkUnavailableError
from emoparse.storage.db import Database
from emoparse.storage.red import RedRepository
from emoparse.storage.runs import RunsRepository


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `network` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "network",
        help="Construye y analiza las redes de interacción de un run de posts.",
        description=(
            "Construye grafos de interacción (reply, mention, rt, qt, "
            "hashtag_co) desde los posts del run, calcula métricas y "
            "comunidades, las persiste en la DB y reporta el acoplamiento "
            "con el análisis emocional. Requiere el extra [network]."
        ),
    )
    p.add_argument(
        "--db",
        required=True,
        help="Path a la DB SQLite del run.",
    )
    p.add_argument(
        "--graphs",
        default="reply,mention,rt,qt,hashtag_co",
        metavar="LISTA",
        help="Grafos a construir, separados por coma. "
             f"Válidos: {', '.join(GRAFOS)}. El grafo '{GRAFO_FOLLOW}' se "
             "adquiere aparte con `emoparse follows` y se mide agregándolo "
             "acá.",
    )
    p.add_argument(
        "--cliques",
        action="store_true",
        help="Reporta las cliques de vínculos recíprocos de cada grafo de "
             "cuentas (todos se vinculan con todos, a diferencia de la "
             "comunidad, que solo es una zona densa).",
    )
    p.add_argument(
        "--min-clique",
        type=int,
        default=3,
        metavar="N",
        help="Tamaño mínimo de clique a reportar (default 3).",
    )
    p.add_argument(
        "--flujo",
        action="store_true",
        help="Circulación de la emoción: contagio por tipo de emoción y "
             "transición fórica partida en intra e inter comunidad.",
    )
    p.add_argument(
        "--similitud",
        action="store_true",
        help="Agrupamiento narrativo: agrupa los simulacros emocionales por "
             "parecido entre sus componentes.",
    )
    p.add_argument(
        "--similitud-componentes",
        default=",".join(sim.COMPONENTES_DEFAULT),
        metavar="LISTA",
        help="Componentes del simulacro que inciden en el parecido, "
             f"separados por coma. Disponibles: {', '.join(sim.COMPONENTES)}.",
    )
    p.add_argument(
        "--similitud-umbral",
        type=float,
        default=sim.UMBRAL_DEFAULT,
        metavar="X",
        help=f"Parecido mínimo para ligar dos simulacros (default {sim.UMBRAL_DEFAULT}).",
    )
    p.add_argument(
        "--semantico",
        action="store_true",
        help="Agrupa los posts por contenido semántico (requiere el extra "
             "[embeddings]).",
    )
    p.add_argument(
        "--modelo-embeddings",
        default=None,
        metavar="NOMBRE",
        help="Modelo de sentence-transformers para --semantico.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed para la detección de comunidades (reproducibilidad).",
    )
    p.add_argument(
        "--profile-graph",
        choices=GRAFOS_AUTOR,
        default=None,
        help="Grafo cuyas comunidades se usan para el perfil emocional. "
             "Por defecto, el primer grafo de autores con comunidades.",
    )
    p.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Directorio para exportar GEXF + CSVs por grafo (Gephi) y el "
             "perfil por comunidad.",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        help="Cantidad de nodos (y de tipos de emoción por comunidad) a "
             "mostrar en los resúmenes.",
    )
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"[network] DB no encontrada: {db_path}")
        return 1

    graphs = tuple(s.strip() for s in args.graphs.split(",") if s.strip())
    unknown = set(graphs) - set(GRAFOS) - {GRAFO_FOLLOW}
    if unknown:
        logger.error(
            f"[network] Grafos desconocidos: {sorted(unknown)}. "
            f"Válidos: {', '.join((*GRAFOS, GRAFO_FOLLOW))}"
        )
        return 1

    db = Database(db_path)
    RunsRepository(db).ensure_migrations()
    df_posts = _read_df(db, "SELECT * FROM posts")
    df_tecno = _read_df(db, "SELECT * FROM tecno_entidades")
    df_emociones = _read_df(db, "SELECT * FROM emociones")

    # Los grafos de interacción se construyen desde los posts; los análisis de
    # similitud (--semantico, --similitud) no. Si el run no trae posts, los
    # grafos de interacción se descartan solos (con aviso) en vez de exigir
    # que el usuario los quite a mano: así `network --semantico --similitud`
    # corre tal cual sobre un corpus de discursos.
    pide_similitud = args.semantico or args.similitud
    if df_posts.empty:
        grafos_interaccion = [
            g for g in graphs if g in GRAFOS or g == GRAFO_FOLLOW
        ]
        if grafos_interaccion and pide_similitud:
            logger.warning(
                "[network] El run no trae posts: se omiten los grafos de "
                f"interacción ({', '.join(grafos_interaccion)}) y se corren "
                "solo los análisis de similitud."
            )
            graphs = tuple(g for g in graphs if g not in grafos_interaccion)
        elif grafos_interaccion:
            logger.error(
                "[network] El run no contiene posts (tabla `posts` vacía). "
                "Los grafos de interacción requieren un corpus de posts. Para "
                "similitud entre discursos, agregá --semantico o --similitud."
            )
            return 1

    logger.info(
        f"[network] Corpus: {len(df_posts)} posts, {len(df_tecno)} "
        f"tecno-entidades, {len(df_emociones)} emociones."
    )

    red_repo = RedRepository(db)
    try:
        comunidades = _procesar_grafos(
            red_repo, df_posts, df_tecno, graphs, args
        )
    except NetworkUnavailableError as e:
        logger.error(f"[network] {e}")
        return 2

    if not df_posts.empty:
        _reporte_emocional(df_posts, df_emociones, comunidades, args)
    if args.similitud:
        _reporte_similitud(db_path, red_repo, df_posts, args)
    if args.semantico:
        _reporte_semantico(red_repo, df_posts, args)
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  Procesamiento
# ══════════════════════════════════════════════════════════════════════════════

def _procesar_grafos(
    red_repo: RedRepository,
    df_posts: pd.DataFrame,
    df_tecno: pd.DataFrame,
    graphs: tuple[str, ...],
    args: argparse.Namespace,
) -> dict[str, dict[str, int]]:
    """Construye, mide, persiste y (opcionalmente) exporta cada grafo.

    Devuelve las comunidades detectadas por grafo (insumo del perfil
    emocional por comunidad).
    """
    construibles = tuple(g for g in graphs if g in GRAFOS)
    df_all = build_edges(df_posts, df_tecno, graphs=construibles)
    comunidades_por_grafo: dict[str, dict[str, int]] = {}

    print()
    for grafo in graphs:
        if grafo == GRAFO_FOLLOW:
            # Adquirido de la plataforma, no derivable del corpus: se lee de
            # donde lo dejó `emoparse follows` y solo se vuelve a medir.
            df_edges = red_repo.load_edges(grafo)
            if df_edges.empty:
                print(
                    f"── {grafo}: sin aristas persistidas. Adquirilo con "
                    "`emoparse follows --db <run> --source <fuente>`."
                )
                continue
        else:
            df_edges = (
                df_all[df_all["grafo"] == grafo]
                if not df_all.empty
                else df_all
            )
        if df_edges.empty:
            print(f"── {grafo}: sin aristas (referencias no capturadas o corpus sin ese tipo de interacción)")
            continue

        directed = grafo != "hashtag_co"
        G = to_graph(df_edges, directed=directed)
        df_metrics = compute_node_metrics(G)
        communities = detect_communities(G, seed=args.seed)
        comunidades_por_grafo[grafo] = communities

        if grafo != GRAFO_FOLLOW:
            red_repo.replace_edges(grafo, df_edges)
        red_repo.replace_metrics(grafo, df_metrics, communities)

        n_com = len(set(communities.values())) if communities else 0
        print(
            f"── {grafo}: {G.number_of_nodes()} nodos, "
            f"{G.number_of_edges()} aristas, {n_com} comunidades"
        )
        top = df_metrics.head(args.top)
        for _, r in top.iterrows():
            com = communities.get(str(r["nodo"]))
            print(
                f"     {r['nodo'][:40]:<42s} pagerank={r['pagerank']:.4f} "
                f"grado={int(r['grado_total'])}"
                + (f" comunidad={com}" if com is not None else "")
            )

        if args.cliques and grafo in GRAFOS_AUTOR:
            _reporte_cliques(G, grafo, args)

        if args.export_dir is not None:
            paths = export_graph(
                G, args.export_dir, grafo,
                node_attrs=df_metrics, communities=communities,
            )
            logger.info(
                f"[network] {grafo}: exportado → "
                + ", ".join(p.name for p in paths)
            )
    print()
    return comunidades_por_grafo


def _reporte_emocional(
    df_posts: pd.DataFrame,
    df_emociones: pd.DataFrame,
    comunidades_por_grafo: dict[str, dict[str, int]],
    args: argparse.Namespace,
) -> None:
    """Reporta el acoplamiento emocional, si hay insumos."""
    if df_emociones.empty:
        logger.info(
            "[network] Sin emociones en el run: se omite el acoplamiento "
            "emocional (corré las stages de emociones y characterizer)."
        )
        return
    foria_map = foria_by_post(df_emociones)
    matrix = foria_transition_matrix(df_posts, foria_map)
    if int(matrix.values.sum()) == 0:
        logger.info(
            "[network] Sin pares padre-hijo con foria caracterizada: se "
            "omite la matriz de transición."
        )
    else:
        print("── Transiciones fóricas en hilos (padre → respuesta):")
        print(matrix.to_string())
        print()
    _reporte_comunidades(df_posts, df_emociones, comunidades_por_grafo, args)
    if args.flujo:
        _reporte_flujo(
            df_posts, df_emociones, foria_map, comunidades_por_grafo, args
        )


def _reporte_comunidades(
    df_posts: pd.DataFrame,
    df_emociones: pd.DataFrame,
    comunidades_por_grafo: dict[str, dict[str, int]],
    args: argparse.Namespace,
) -> None:
    """Reporta el perfil emocional de las comunidades de un grafo de autores."""
    candidatos = [args.profile_graph] if args.profile_graph else GRAFOS_AUTOR
    grafo = next((g for g in candidatos if comunidades_por_grafo.get(g)), None)
    if grafo is None:
        logger.info(
            "[network] Sin comunidades en "
            f"{args.profile_graph or 'ningún grafo de autores'}: se omite el "
            "perfil emocional por comunidad."
        )
        return

    perfil = community_emotion_profile(
        df_posts, comunidades_por_grafo[grafo], df_emociones
    )
    if perfil.empty:
        logger.info(
            f"[network] Ninguna emoción cae en las comunidades de {grafo}: "
            "se omite el perfil emocional por comunidad."
        )
        return

    print(f"── Perfil emocional por comunidad ({grafo}):")
    for comunidad, grp in perfil.groupby("comunidad", sort=True):
        tipos = ", ".join(
            f"{r['tipo_emocion']} ({int(r['n'])})"
            for _, r in grp.head(args.top).iterrows()
        )
        forias = " ".join(
            f"{f}={int(grp[f].sum())}" for f in FORIAS if int(grp[f].sum())
        )
        print(f"     comunidad {comunidad}: {int(grp['n'].sum())} emociones")
        print(f"       tipos:  {tipos}")
        print(f"       forias: {forias}")
    print()

    if args.export_dir is not None:
        path = export_table(
            perfil, args.export_dir, f"perfil_comunidades_{grafo}"
        )
        logger.info(f"[network] perfil por comunidad: exportado → {path.name}")


def _reporte_cliques(G, grafo: str, args: argparse.Namespace) -> None:
    """Cliques de vínculos recíprocos de un grafo de cuentas."""
    cliques = detect_cliques(G, min_size=args.min_clique, mutual_only=True)
    if not cliques:
        print(
            f"     cliques: ninguna de {args.min_clique}+ cuentas con "
            "vínculo recíproco"
        )
        return
    print(f"     cliques (vínculo recíproco, {len(cliques)} de "
          f"{args.min_clique}+ cuentas):")
    for c in cliques[:args.top]:
        print(f"       {len(c)}: {', '.join(n[:28] for n in c[:8])}"
              + (" …" if len(c) > 8 else ""))
    if args.export_dir is not None:
        export_table(
            pd.DataFrame([
                {"tamanio": len(c), "cuentas": "; ".join(c)} for c in cliques
            ]),
            args.export_dir, f"cliques_{grafo}",
        )


def _reporte_flujo(
    df_posts: pd.DataFrame,
    df_emociones: pd.DataFrame,
    foria_map: dict[str, str],
    comunidades_por_grafo: dict[str, dict[str, int]],
    args: argparse.Namespace,
) -> None:
    """Circulación de la emoción: contagio por tipo y transición por alcance."""
    tipos = tipos_por_post(df_emociones)
    lift = contagion_lift(df_posts, tipos)
    if lift.empty:
        logger.info(
            "[network] Sin pares padre-respuesta con emociones suficientes: "
            "se omite el contagio por tipo."
        )
    else:
        print("── Contagio por tipo de emoción (lift > 1: se replica más de "
              "lo esperable):")
        print(lift.head(args.top).to_string(index=False))
        print()
        if args.export_dir is not None:
            export_table(lift, args.export_dir, "contagio_por_tipo")

    grafo = next(
        (g for g in GRAFOS_AUTOR if comunidades_por_grafo.get(g)), None
    )
    if grafo is None:
        logger.info(
            "[network] Sin comunidades de cuentas: se omite la circulación "
            "entre comunidades."
        )
        return
    comunidades = comunidades_por_grafo[grafo]

    matrices = foria_transition_by_scope(df_posts, foria_map, comunidades)
    for alcance, matriz in matrices.items():
        if int(matriz.values.sum()) == 0:
            continue
        etiqueta = (
            "dentro de la misma comunidad" if alcance == "intra"
            else "entre comunidades distintas"
        )
        print(f"── Transiciones fóricas {etiqueta} ({grafo}):")
        print(matriz.to_string())
        print()
        if args.export_dir is not None:
            export_table(
                matriz.reset_index(names="foria_padre"),
                args.export_dir, f"transicion_forica_{alcance}_{grafo}",
            )

    flujo = flujo_entre_comunidades(df_posts, foria_map, comunidades)
    if flujo.empty:
        return
    print(f"── Circulación entre comunidades ({grafo}):")
    print(flujo.head(args.top).to_string(index=False))
    print()
    if args.export_dir is not None:
        export_table(flujo, args.export_dir, f"flujo_comunidades_{grafo}")


def _reporte_similitud(
    db_path: Path,
    red_repo: RedRepository,
    df_posts: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    """Agrupamiento narrativo por parecido entre simulacros emocionales.

    Los simulacros se leen con la misma resolución de referentes canónicos
    que usan las tabs y el export, para no duplicar ese criterio. El grafo de
    parecido se persiste como un grafo más: sus nodos son emociones, no
    cuentas, pero se miden y se exportan igual.
    """
    from emoparse.storage.simulacros import get_emociones_enriched

    df = get_emociones_enriched(db_path)
    if df.empty:
        logger.info(
            "[network] El run no tiene emociones: se omite el agrupamiento "
            "narrativo."
        )
        return
    componentes = [
        c.strip() for c in args.similitud_componentes.split(",") if c.strip()
    ]
    disponibles = sim.componentes_disponibles(df)
    faltan = [c for c in componentes if c not in disponibles]
    if faltan:
        logger.warning(
            f"[network] Componentes sin datos en este run: {faltan}. "
            "Los ignoro (¿faltó correr actants, characterizer o semas?)."
        )
        componentes = [c for c in componentes if c in disponibles]
    if not componentes:
        logger.error(
            "[network] Ningún componente pedido tiene datos en este run."
        )
        return

    try:
        features = sim.build_features(df, componentes)
    except sim.ComponenteDesconocidoError as e:
        logger.error(f"[network] {e}")
        return
    pares = sim.similarity_pairs(features, umbral=args.similitud_umbral)
    if pares.empty:
        logger.info(
            f"[network] Ningún par de simulacros alcanza el umbral "
            f"{args.similitud_umbral}: probá bajarlo o usar menos componentes."
        )
        return
    grupos = sim.agrupar(pares, len(df), seed=args.seed)

    claves = [sim.clave_simulacro(r) for r in df.to_dict(orient="records")]
    df_edges = pd.DataFrame({
        "grafo": "simulacro",
        "origen": [claves[int(i)] for i in pares["i"]],
        "destino": [claves[int(j)] for j in pares["j"]],
        "post_id": [str(df.iloc[int(i)]["codigo"]) for i in pares["i"]],
        "peso": pares["similitud"].astype(float),
        "fecha": None,
    })
    red_repo.replace_edges("simulacro", df_edges)
    G = to_graph(df_edges, directed=False)
    red_repo.replace_metrics(
        "simulacro", compute_node_metrics(G),
        {claves[i]: g for i, g in grupos.items()},
    )

    perfil = sim.perfil_grupos(df, grupos, componentes)
    print(f"── Agrupamiento narrativo ({len(grupos)} de {len(df)} simulacros "
          f"agrupados en {perfil.shape[0]} grupo(s)):")
    print(f"     componentes: {', '.join(componentes)}")
    print(perfil.head(args.top).to_string(index=False))
    print()

    autor_por_unidad = {
        str(r["post_id"]): str(r["autor_handle"])
        for r in df_posts.to_dict(orient="records")
    } if not df_posts.empty else {}
    if autor_por_unidad:
        autores = sim.grupos_por_autor(df, grupos, autor_por_unidad)
        if not autores.empty:
            print("── Cuentas por grupo narrativo:")
            print(autores.head(args.top).to_string(index=False))
            print()
    if args.export_dir is not None:
        export_table(perfil, args.export_dir, "grupos_narrativos")
        if autor_por_unidad:
            export_table(
                sim.grupos_por_autor(df, grupos, autor_por_unidad),
                args.export_dir, "grupos_narrativos_por_autor",
            )
        export_table(pares, args.export_dir, "parecido_simulacros")


def _reporte_semantico(
    red_repo: RedRepository,
    df_posts: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    """Agrupamiento de posts por contenido, con embeddings."""
    from emoparse.network import embeddings as emb

    kwargs = {"seed": args.seed}
    if args.modelo_embeddings:
        kwargs["modelo"] = args.modelo_embeddings
    try:
        aristas, comunidades = emb.agrupar_por_contenido(df_posts, **kwargs)
    except emb.EmbeddingsUnavailableError as e:
        logger.error(f"[network] {e}")
        return
    if not comunidades:
        logger.info(
            "[network] Ningún par de posts supera el umbral semántico: se "
            "omite el agrupamiento por contenido."
        )
        return

    df_edges = aristas.assign(grafo="semantico", post_id=None, fecha=None)[
        ["grafo", "origen", "destino", "post_id", "peso", "fecha"]
    ]
    red_repo.replace_edges("semantico", df_edges)
    G = to_graph(df_edges, directed=False)
    red_repo.replace_metrics("semantico", compute_node_metrics(G), comunidades)

    terminos = emb.terminos_por_comunidad(df_posts, comunidades)
    n_com = len(set(comunidades.values()))
    print(f"── Comunidades semánticas ({len(comunidades)} posts en {n_com}):")
    print(terminos.head(args.top).to_string(index=False))
    print()
    if args.export_dir is not None:
        export_table(terminos, args.export_dir, "comunidades_semanticas")


def _read_df(db: Database, sql: str) -> pd.DataFrame:
    """Lee una consulta completa a DataFrame (tabla ausente → DF vacío)."""
    try:
        rows = db.execute(sql).fetchall()
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])
