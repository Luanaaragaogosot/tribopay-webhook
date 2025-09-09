import asyncio
import aiohttp
import sqlite3
from io import BytesIO
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ================= CONFIGURAÇÕES =================
TELEGRAM_TOKEN = "<8448490650:AAGbA--aGsR-opTk5Cgqmk0Ds1b5EOUoXC8>"
TRIBOPAY_TOKEN = "<8tXfMo2cM8aWPCMYstsb5Sycb6JVGM8Cd7NbrAt8nYmeCZ1ing13hXPxdBA5>"
WEBHOOK_URL = "https://tribopay-webhook.onrender.com/webhook/tribopay"

TAXA_PERCENTUAL = 5
VALOR_MINIMO = 10
VALOR_MAXIMO = 2000

API_TRIBOPAY = "https://api.tribopay.com.br/api/public/v1/transactions"

# ================= BANCO DE DADOS =================
DB_NAME = "evil_bank.db"
conn = sqlite3.connect(DB_NAME, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    nome TEXT,
    saldo REAL DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tipo TEXT,
    valor REAL,
    taxa REAL,
    status TEXT,
    pix_code TEXT,
    qr_url TEXT,
    descricao TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")
conn.commit()

# ================= FUNÇÕES AUXILIARES =================
def calcular_taxa(valor):
    return round(valor * TAXA_PERCENTUAL / 100, 2)

def get_user(telegram_id, nome=None):
    cursor.execute("SELECT id, saldo FROM users WHERE telegram_id=?", (telegram_id,))
    result = cursor.fetchone()
    if result:
        return {"id": result[0], "saldo": result[1]}
    else:
        cursor.execute("INSERT INTO users (telegram_id, nome) VALUES (?, ?)", (telegram_id, nome))
        conn.commit()
        return get_user(telegram_id, nome)

def add_transaction(user_id, tipo, valor, taxa, status, pix_code=None, qr_url=None, descricao=""):
    cursor.execute("""
        INSERT INTO transactions (user_id, tipo, valor, taxa, status, pix_code, qr_url, descricao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, tipo, valor, taxa, status, pix_code, qr_url, descricao))
    conn.commit()

def update_transaction_status(pix_code, status):
    cursor.execute("UPDATE transactions SET status=? WHERE pix_code=?", (status, pix_code))
    conn.commit()

def update_user_saldo(user_id, valor):
    cursor.execute("UPDATE users SET saldo = saldo + ? WHERE id=?", (valor, user_id))
    conn.commit()

# ================= BOTÕES =================
def menu_inicial():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Depositar", callback_data="depositar")],
        [InlineKeyboardButton("Saldo", callback_data="saldo")],
        [InlineKeyboardButton("Histórico", callback_data="historico")],
        [InlineKeyboardButton("Dúvidas", callback_data="duvidas")]
    ])

# ================= COMANDOS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    nome = update.message.from_user.full_name
    get_user(telegram_id, nome)

    await update.message.reply_text(
        f"""Bem-vindo ao *Evil Bank*.

Aqui você terá total privacidade e anonimato, com a menor taxa do mercado ({TAXA_PERCENTUAL}% por depósito).

Por favor, escolha uma opção:""",
        parse_mode="Markdown",
        reply_markup=menu_inicial()
    )

async def duvidas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"""*Perguntas Frequentes*

1. Depósitos: taxa de {TAXA_PERCENTUAL}% aplicada automaticamente.  
2. Limites: mínimo R${VALOR_MINIMO}, máximo R${VALOR_MAXIMO}.  
3. Privacidade: total anonimato garantido.  
4. Confirmação: saldo atualizado imediatamente após pagamento via PIX.""",
        parse_mode="Markdown"
    )

# ================= CALLBACK HANDLER =================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    telegram_id = query.from_user.id
    nome = query.from_user.full_name
    user = get_user(telegram_id, nome)

    await query.answer()

    if data == "depositar":
        context.user_data["etapa"] = "deposito_valor"
        await query.message.reply_text(f"Informe o valor do depósito (R${VALOR_MINIMO} - R${VALOR_MAXIMO}):")
    elif data == "saldo":
        await query.message.reply_text(f"Seu saldo atual é: R${user['saldo']:.2f}")
    elif data == "historico":
        cursor.execute("SELECT tipo, valor, taxa, status, created_at FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user["id"],))
        rows = cursor.fetchall()
        if not rows:
            await query.message.reply_text("Nenhuma transação encontrada.")
        else:
            msg = "Últimas transações:\n\n"
            for r in rows:
                msg += f"{r[4]} | {r[0].capitalize()} | Valor: R${r[1]:.2f} | Taxa: R${r[2]:.2f} | Status: {r[3]}\n"
            await query.message.reply_text(msg)
    elif data == "duvidas":
        await duvidas(update, context)

# ================= COLETA DE DADOS =================
async def coleta_dados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    etapa = context.user_data.get("etapa")
    telegram_id = update.message.from_user.id
    nome = update.message.from_user.full_name
    user = get_user(telegram_id, nome)
    texto = update.message.text.strip().replace(",", ".")

    if etapa == "deposito_valor":
        try:
            valor = float(texto)
            if valor < VALOR_MINIMO or valor > VALOR_MAXIMO:
                await update.message.reply_text(f"Valor inválido. Informe um valor entre R${VALOR_MINIMO} e R${VALOR_MAXIMO}.")
                return
            taxa = calcular_taxa(valor)
            valor_final = valor + taxa
            context.user_data["deposito_valor"] = valor
            context.user_data["deposito_taxa"] = taxa
            context.user_data["deposito_final"] = valor_final
            context.user_data["etapa"] = "gerar_pagamento"
            await gerar_pagamento(update, context)
        except ValueError:
            await update.message.reply_text("Valor inválido. Insira um número válido.")

# ================= GERAR PAGAMENTO PIX =================
async def gerar_pagamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    valor = context.user_data["deposito_valor"]
    taxa = context.user_data["deposito_taxa"]
    valor_final = context.user_data["deposito_final"]
    user = get_user(update.message.from_user.id)

    body = {
        "amount": int(valor_final*100),  # valor em centavos
        "offer_hash": "EVILBANK_DEPOSITO",
        "payment_method": "pix",
        "customer": {
            "name": update.message.from_user.full_name,
            "email": f"{update.message.from_user.id}@evilbank.com",
            "phone_number": "0000000000",
            "document": "00000000000",
            "street_name": "Rua Teste",
            "number": "0",
            "complement": "",
            "neighborhood": "Centro",
            "city": "Cidade",
            "state": "UF",
            "zip_code": "00000000"
        },
        "cart": [
            {
                "product_hash": "EVILBANK_DEPOSITO",
                "title": "Depósito Evil Bank",
                "cover": None,
                "price": int(valor_final*100),
                "quantity": 1,
                "operation_type": 1,
                "tangible": False
            }
        ],
        "expire_in_days": 1,
        "transaction_origin": "api",
        "postback_url": WEBHOOK_URL
    }

    headers = {"Authorization": f"Bearer {TRIBOPAY_TOKEN}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(API_TRIBOPAY, headers=headers, json=body) as resp:
            data = await resp.json()
            pix_code = data.get("pix_code")
            qr_url = data.get("pix_qr_code")
            transacao_id = data.get("id")
            if pix_code and qr_url:
                add_transaction(user["id"], "depósito", valor, taxa, "pendente", pix_code, qr_url, f"Transação ID: {transacao_id}")
                await update.message.reply_text(
                    f"Depósito gerado com sucesso!\nValor: R${valor:.2f}\nTaxa: R${taxa:.2f}\nTotal: R${valor_final:.2f}\nCódigo PIX:\n`{pix_code}`",
                    parse_mode="Markdown"
                )
                async with aiohttp.ClientSession() as session2:
                    img_data = await session2.get(qr_url)
                    img_bytes = await img_data.read()
                    await update.message.reply_photo(InputFile(BytesIO(img_bytes), filename="qrcode.png"),
                                                   caption="Escaneie o QR Code no seu app bancário.")
            else:
                await update.message.reply_text("Erro ao gerar pagamento. Verifique os dados e tente novamente.")

# ================= FLASK PARA WEBHOOK =================
app = Flask(__name__)

@app.route("/webhook/tribopay", methods=["POST"])
def tribopay_webhook():
    data = request.json
    pix_code = data.get("pix_code")
    status = data.get("status")  # "approved", "pending", etc.
    cursor.execute("SELECT user_id, valor, taxa FROM transactions WHERE pix_code=?", (pix_code,))
    row = cursor.fetchone()
    if row and status == "approved":
        user_id, valor, taxa = row
        update_transaction_status(pix_code, "aprovado")
        update_user_saldo(user_id, valor)
    return jsonify({"success": True})

# ================= MAIN =================
def main():
    loop = asyncio.get_event_loop()
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, coleta_dados))

    print("Bot rodando...")
    application.run_polling()

if __name__ == "__main__":
    main()
