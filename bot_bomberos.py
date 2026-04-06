import os
import logging
import gspread
from datetime import datetime
from dotenv import load_dotenv  # <-- LIBRERÍA AGREGADA
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# 1. CARGAR SECRETOS DESDE EL ARCHIVO .env
load_dotenv()

# ---------------------------------------------------------
# CONFIGURACIÓN BÁSICA
# ---------------------------------------------------------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ⚠️ AHORA EL BOT BUSCA ESTOS VALORES EN EL ARCHIVO .env (SEGURO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
NOMBRE_PLANILLA = os.getenv("NOMBRE_HOJA")

# ---------------------------------------------------------
# CONEXIÓN A GOOGLE SHEETS
# ---------------------------------------------------------
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
    client = gspread.authorize(creds)
    return client.open(NOMBRE_PLANILLA).sheet1

sheet = conectar_google_sheets()

# ---------------------------------------------------------
# ESTADOS DE LA CONVERSACIÓN
# ---------------------------------------------------------
UNIDAD, KM_SALIDA, PERSONAL = range(3)

# ---------------------------------------------------------
# LÓGICA DEL BOT
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teclado_unidades = [['B-1', 'R-1'], ['Q-1', 'Z-1'], ['Cancelar']]
    markup = ReplyKeyboardMarkup(teclado_unidades, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "🚨 *Sistema de Registro Bomberil* 🚨\n"
        "Iniciando reporte...\n\n"
        "¿Qué unidad sale a la emergencia?",
        reply_markup=markup,
        parse_mode='Markdown'
    )
    return UNIDAD

async def recibir_unidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    if texto == 'Cancelar':
        await update.message.reply_text("Registro cancelado.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    context.user_data['unidad'] = texto
    
    await update.message.reply_text(
        f"✅ Unidad *{texto}* registrada.\n\n"
        "Indique el *Kilometraje de salida* (solo números):",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    return KM_SALIDA

async def recibir_km(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['km_salida'] = update.message.text
    await update.message.reply_text(
        "🔢 Kilometraje guardado.\n\n"
        "Por último, ingrese el *personal a bordo* (nombres o cargos separados por coma):",
        parse_mode='Markdown'
    )
    return PERSONAL

async def finalizar_y_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    personal = update.message.text
    unidad = context.user_data['unidad']
    km_salida = context.user_data['km_salida']
    
    fecha_hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    await update.message.reply_text("⏳ Guardando datos en la nube...")

    try:
        sheet.append_row([fecha_hora, unidad, km_salida, personal])
        await update.message.reply_text(
            f"🏁 *¡Registro Completado Exitosamente!*\n\n"
            f"📅 Fecha: {fecha_hora}\n"
            f"🚒 Unidad: {unidad}\n"
            f"🛣️ KM: {km_salida}\n"
            f"👨‍🚒 Personal: {personal}\n\n"
            "La base de datos ha sido actualizada.",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ocurrió un error al guardar en Google Sheets:\n{e}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Proceso cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ---------------------------------------------------------
# ARRANQUE DEL BOT
# ---------------------------------------------------------
if __name__ == '__main__':
    # Validación por si el .env no se cargó bien
    if not TOKEN:
        print("❌ ERROR: No se encontró el TOKEN. Revisa tu archivo .env")
        exit()

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            UNIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_unidad)],
            KM_SALIDA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_km)],
            PERSONAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalizar_y_guardar)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel), 
            MessageHandler(filters.Regex('^Cancelar$'), cancel)
        ],
    )

    app.add_handler(conv_handler)
    
    print("🚒 Bot encendido y protegido de forma segura... Presiona Ctrl+C para detenerlo.")
    app.run_polling()