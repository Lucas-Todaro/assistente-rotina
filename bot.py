# -*- coding: utf-8 -*-

import os
import hashlib
import json
from datetime import datetime, timedelta, time
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from supabase import create_client
from google import genai
import numpy as np

# ===== Configuração =====
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

variaveis_obrigatorias = {
    "TELEGRAM_TOKEN": TOKEN,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
}
variaveis_faltando = [
    nome for nome, valor in variaveis_obrigatorias.items() if not valor
]
if variaveis_faltando:
    raise RuntimeError(
        f"Variáveis de ambiente ausentes: {', '.join(variaveis_faltando)}"
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

AGUARDANDO_DURACAO = 1
DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
DIAS_FIM_DE_SEMANA = ["sabado", "domingo"]
BASE_DIR = Path(__file__).resolve().parent
EXEMPLOS_PATH = BASE_DIR / "category_examples.json"
CACHE_EMBEDDINGS_PATH = BASE_DIR / "category_centers.json"
EMBEDDING_MODEL = "gemini-embedding-001"
CACHE_VERSION = 1

with EXEMPLOS_PATH.open("r", encoding="utf-8") as arquivo_exemplos:
    EXEMPLOS_CATEGORIAS = json.load(arquivo_exemplos)

CATEGORIAS = set(EXEMPLOS_CATEGORIAS)
CENTROS_CATEGORIAS = {}


# ===== Classificação por embeddings =====
def assinatura_dos_exemplos():
    conteudo = {
        "cache_version": CACHE_VERSION,
        "model": EMBEDDING_MODEL,
        "examples": EXEMPLOS_CATEGORIAS,
    }
    serializado = json.dumps(
        conteudo,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def gerar_embeddings(textos):
    resultado = gemini_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=textos,
    )
    return np.asarray(
        [embedding.values for embedding in resultado.embeddings],
        dtype=np.float32,
    )


def gerar_embedding(texto):
    return gerar_embeddings([texto])[0]


def normalizar_vetor(vetor):
    norma = np.linalg.norm(vetor)
    return vetor if norma == 0 else vetor / norma


def carregar_centros_do_cache():
    if not CACHE_EMBEDDINGS_PATH.exists():
        return False

    try:
        cache = json.loads(CACHE_EMBEDDINGS_PATH.read_text(encoding="utf-8"))
        if cache.get("examples_hash") != assinatura_dos_exemplos():
            print("Cache de embeddings desatualizado.")
            return False
        if cache.get("model") != EMBEDDING_MODEL:
            return False

        centros = cache.get("centers", {})
        if set(centros) != CATEGORIAS:
            return False

        CENTROS_CATEGORIAS.clear()
        CENTROS_CATEGORIAS.update({
            categoria: normalizar_vetor(np.asarray(vetor, dtype=np.float32))
            for categoria, vetor in centros.items()
        })
        print("Centros das categorias carregados do cache.")
        return True
    except (OSError, ValueError, TypeError) as erro:
        print(f"Não foi possível carregar o cache de embeddings: {erro}")
        return False


def salvar_centros_no_cache():
    cache = {
        "cache_version": CACHE_VERSION,
        "model": EMBEDDING_MODEL,
        "examples_hash": assinatura_dos_exemplos(),
        "centers": {
            categoria: centro.tolist()
            for categoria, centro in CENTROS_CATEGORIAS.items()
        },
    }
    temporario = CACHE_EMBEDDINGS_PATH.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporario.replace(CACHE_EMBEDDINGS_PATH)
    print(f"Cache de embeddings salvo em {CACHE_EMBEDDINGS_PATH.name}.")


def calcular_centros_categorias(forcar=False):
    if not forcar and carregar_centros_do_cache():
        return

    print("Calculando centros das categorias...")
    CENTROS_CATEGORIAS.clear()

    for categoria, exemplos in EXEMPLOS_CATEGORIAS.items():
        embeddings = gerar_embeddings(exemplos)
        centro = normalizar_vetor(np.mean(embeddings, axis=0))
        CENTROS_CATEGORIAS[categoria] = centro

    salvar_centros_no_cache()
    print("Centros calculados com sucesso.")


def cosine_similarity(a, b):
    return float(np.dot(normalizar_vetor(a), normalizar_vetor(b)))


def categorizar(texto_tarefa):
    embedding_tarefa = gerar_embedding(texto_tarefa)
    return max(
        CENTROS_CATEGORIAS,
        key=lambda categoria: cosine_similarity(
            embedding_tarefa,
            CENTROS_CATEGORIAS[categoria],
        ),
    )

# ===== Lógica de sugestão de horário =====
def buscar_rotina_fixa_vigente(data_referencia):
    resultado = supabase.table("rotina_fixa").select("*").execute()
    blocos_validos = []

    for bloco in resultado.data:
        data_inicio = bloco.get("data_inicio")
        data_fim = bloco.get("data_fim")

        if data_inicio and data_referencia < datetime.strptime(data_inicio, "%Y-%m-%d").date():
            continue
        if data_fim and data_referencia > datetime.strptime(data_fim, "%Y-%m-%d").date():
            continue

        blocos_validos.append(bloco)

    return blocos_validos

def buscar_tarefas_agendadas(data_referencia):
    """Busca tarefas pendentes que já têm dia/horário sugerido para essa data."""
    resultado = supabase.table("tarefas") \
        .select("*") \
        .eq("dia_sugerido", data_referencia.isoformat()) \
        .eq("status", "pendente") \
        .execute()
    return resultado.data

def calcular_janelas_livres(dias_a_frente=7):
    janelas_livres = []
    agora = datetime.now()
    hoje = agora.date()

    for i in range(dias_a_frente):
        data_atual = hoje + timedelta(days=i)
        dia_semana_nome = DIAS_SEMANA[data_atual.weekday()]

        if dia_semana_nome in DIAS_FIM_DE_SEMANA:
            inicio_dia = time(9, 0)
        else:
            inicio_dia = time(6, 0)

        fim_dia = time(23, 0)

        if data_atual == hoje:
            hora_atual = agora.time()
            cursor = max(inicio_dia, hora_atual)
        else:
            cursor = inicio_dia

        if cursor >= fim_dia:
            continue

        blocos_do_dia = [
            {"horario_inicio": b["horario_inicio"], "horario_fim": b["horario_fim"]}
            for b in buscar_rotina_fixa_vigente(data_atual)
            if b["dia_semana"] == dia_semana_nome
        ]

        tarefas_do_dia = buscar_tarefas_agendadas(data_atual)
        for tarefa in tarefas_do_dia:
            if not tarefa.get("horario_sugerido") or not tarefa.get("duracao_minutos"):
                continue
            inicio = tarefa["horario_sugerido"]
            duracao = tarefa["duracao_minutos"]
            inicio_dt = datetime.strptime(inicio, "%H:%M:%S")
            fim_dt = inicio_dt + timedelta(minutes=duracao)
            blocos_do_dia.append({
                "horario_inicio": inicio,
                "horario_fim": fim_dt.strftime("%H:%M:%S")
            })

        blocos_do_dia.sort(key=lambda b: b["horario_inicio"])

        for bloco in blocos_do_dia:
            horario_inicio_bloco = datetime.strptime(bloco["horario_inicio"], "%H:%M:%S").time()
            horario_fim_bloco = datetime.strptime(bloco["horario_fim"], "%H:%M:%S").time()

            if horario_fim_bloco <= cursor:
                continue

            if cursor < horario_inicio_bloco:
                janelas_livres.append({
                    "data": data_atual,
                    "dia_semana": dia_semana_nome,
                    "inicio": cursor,
                    "fim": horario_inicio_bloco
                })

            cursor = max(cursor, horario_fim_bloco)

        if cursor < fim_dia:
            janelas_livres.append({
                "data": data_atual,
                "dia_semana": dia_semana_nome,
                "inicio": cursor,
                "fim": fim_dia
            })

    janelas_filtradas = []
    for janela in janelas_livres:
        if janela["dia_semana"] in ["terca", "quinta"]:
            if janela["inicio"] >= time(12, 0) and janela["fim"] <= time(14, 0):
                continue
        janelas_filtradas.append(janela)

    return janelas_filtradas

def duracao_janela_minutos(janela):
    inicio_dt = datetime.combine(janela["data"], janela["inicio"])
    fim_dt = datetime.combine(janela["data"], janela["fim"])
    return (fim_dt - inicio_dt).total_seconds() / 60

def sugerir_horario(duracao_minutos_tarefa):
    janelas = calcular_janelas_livres()
    for janela in janelas:
        if duracao_janela_minutos(janela) >= duracao_minutos_tarefa:
            return janela
    return None

# ===== Handlers do Telegram =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot conectado! Me manda uma tarefa pra testar.")

async def nova_tarefa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    categoria = categorizar(texto)

    context.user_data["descricao"] = texto
    context.user_data["categoria"] = categoria

    teclado = [
        [
            InlineKeyboardButton("15 min", callback_data="15"),
            InlineKeyboardButton("30 min", callback_data="30"),
        ],
        [
            InlineKeyboardButton("1 hora", callback_data="60"),
            InlineKeyboardButton("2h ou mais", callback_data="120"),
        ]
    ]
    await update.message.reply_text(
        f"Categoria: {categoria}\nQuanto tempo isso deve levar?",
        reply_markup=InlineKeyboardMarkup(teclado)
    )
    return AGUARDANDO_DURACAO

async def receber_duracao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    duracao_minutos = int(query.data)
    descricao = context.user_data.get("descricao")
    categoria = context.user_data.get("categoria")

    janela_sugerida = sugerir_horario(duracao_minutos)

    if janela_sugerida:
        dia_sugerido = janela_sugerida["data"]
        horario_sugerido = janela_sugerida["inicio"]
        texto_sugestao = f"\n\nSugestão: {janela_sugerida['dia_semana']} ({dia_sugerido.strftime('%d/%m')}) às {horario_sugerido.strftime('%H:%M')}"
    else:
        dia_sugerido = None
        horario_sugerido = None
        texto_sugestao = "\n\nNão encontrei uma janela livre nos próximos dias."

    supabase.table("tarefas").insert({
        "descricao": descricao,
        "categoria": categoria,
        "duracao_minutos": duracao_minutos,
        "status": "pendente",
        "dia_sugerido": dia_sugerido.isoformat() if dia_sugerido else None,
        "horario_sugerido": horario_sugerido.strftime("%H:%M:%S") if horario_sugerido else None
    }).execute()

    await query.edit_message_text(
        f"Tarefa salva: {descricao}\nCategoria: {categoria}\nDuração: {duracao_minutos} min{texto_sugestao}"
    )
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado.")
    return ConversationHandler.END

# ===== Inicialização =====
def main():
    calcular_centros_categorias()

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, nova_tarefa)],
        states={
            AGUARDANDO_DURACAO: [CallbackQueryHandler(receber_duracao)]
        },
        fallbacks=[CommandHandler("cancelar", cancelar)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
