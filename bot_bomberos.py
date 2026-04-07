import os
import logging
import gspread
import re 
from datetime import datetime
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ID_PLANILLA = os.getenv("ID_PLANILLA")

# 1. FUNCIÓN DE CONEXIÓN CORREGIDA (Devuelve el cliente)
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
    return gspread.authorize(creds)

# 2. INICIALIZACIÓN DE CONEXIONES
gc = conectar_google_sheets()
archivo_excel = gc.open_by_key(ID_PLANILLA)
sheet = archivo_excel.sheet1                    # Hoja de datos (Parte 10-0)
user_sheet = archivo_excel.worksheet("Usuarios") # Hoja de voluntarios

def obtener_mapa_usuarios():
    """Trae los datos de la pestaña Usuarios y los convierte en diccionario"""
    try:
        registros = user_sheet.get_all_records()
        return {str(r['ID']): r['Nombre'] for r in registros}
    except Exception as e:
        print(f"⚠️ Error al leer lista de usuarios: {e}")
        return {}

# ESTADOS
UNIDAD, CLAVE, KM_SALIDA, UBICACION, KM_LLEGADA, PERSONAL, APOYO, AFECTADOS, DETALLES = range(9)

# ---------------------------------------------------------
# LÓGICA DEL BOT
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    usuarios_mapa = obtener_mapa_usuarios()
    
    if user_id not in usuarios_mapa:
        await update.message.reply_text("⛔ Acceso denegado. No estás autorizado en la planilla.")
        return ConversationHandler.END

    # Guardamos el nombre del responsable para el reporte final
    context.user_data['responsable'] = usuarios_mapa[user_id]
    
    context.user_data['fecha'] = datetime.now().strftime("%d/%m/%Y")
    context.user_data['hora'] = datetime.now().strftime("%H:%M:%S")
    context.user_data['lista_apoyo'] = []
    context.user_data['lista_afectados'] = []
    
    teclado_unidades = [['B-2', 'R-2'], ['BF-2'], ['Cancelar']]
    await update.message.reply_text(
        f"🚨 *Nuevo Parte de Emergencia* 🚨\n\nResponsable: *{context.user_data['responsable']}*\n\n¿Qué unidad sale?",
        reply_markup=ReplyKeyboardMarkup(teclado_unidades, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='Markdown'
    )
    return UNIDAD

async def recibir_unidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    if texto == 'Cancelar':
        await update.message.reply_text("Registro cancelado.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    context.user_data['unidad'] = texto
    teclado_claves = [['10-0', '10-2'], ['10-3', '10-4'], ['10-14', 'Otra Clave']]
    await update.message.reply_text(
        f"✅ Unidad *{texto}*.\n\nIndique la *Clave del Llamado*:",
        reply_markup=ReplyKeyboardMarkup(teclado_claves, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='Markdown'
    )
    return CLAVE

async def recibir_clave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    if texto == 'Otra Clave':
        await update.message.reply_text("✍️ *Escriba la clave radial manualmente*:", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
        return CLAVE 
    context.user_data['clave'] = texto
    await update.message.reply_text(f"✅ Clave *{texto}*.\n\n*Kilometraje de salida* (solo números):", parse_mode='Markdown')
    return KM_SALIDA

async def recibir_km_salida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("❌ Ingrese *solo números* para el KM de salida:")
        return KM_SALIDA
    context.user_data['km_salida'] = texto
    boton_ubicacion = KeyboardButton("📍 Enviar mi ubicación actual", request_location=True)
    await update.message.reply_text(
        "📍 *Ubicación*\nEnvía GPS o escribe dirección:",
        reply_markup=ReplyKeyboardMarkup([[boton_ubicacion]], one_time_keyboard=True, resize_keyboard=True),
        parse_mode='Markdown'
    )
    return UBICACION

async def recibir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        lat, lon = update.message.location.latitude, update.message.location.longitude
        context.user_data['ubicacion'] = f"http://maps.google.com/maps?q={lat},{lon}"
    else:
        context.user_data['ubicacion'] = update.message.text
    await update.message.reply_text("✅ Ubicación recibida.\n\nIndique *Kilometraje de llegada*:", reply_markup=ReplyKeyboardRemove())
    return KM_LLEGADA

async def recibir_km_llegada(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("❌ Ingrese *solo números*:")
        return KM_LLEGADA
    km_l = int(texto)
    km_s = int(context.user_data.get('km_salida', 0))
    if km_l < km_s:
        await update.message.reply_text(f"❌ Error: Llegada ({km_l}) menor que Salida ({km_s}). Reintente:")
        return KM_LLEGADA
    context.user_data['km_llegada'] = str(km_l)
    await update.message.reply_text("👨‍🚒 Ingrese los *nombres del personal* a bordo:", parse_mode='Markdown')
    return PERSONAL

async def recibir_personal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['personal'] = update.message.text
    await update.message.reply_text("🚓 *Apoyo Concurrente*:", reply_markup=ReplyKeyboardMarkup([['Sin Apoyo']], one_time_keyboard=True, resize_keyboard=True), parse_mode='Markdown')
    return APOYO

async def recibir_apoyo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    if texto in ['Sin Apoyo', '✅ Siguiente paso']:
        await update.message.reply_text("🏥 *Personas Afectadas*:", reply_markup=ReplyKeyboardMarkup([['Sin Afectados']], one_time_keyboard=True, resize_keyboard=True), parse_mode='Markdown')
        return AFECTADOS
    context.user_data['lista_apoyo'].append(texto)
    await update.message.reply_text("✔️ Registrado. ¿Otro? o '✅ Siguiente paso'", reply_markup=ReplyKeyboardMarkup([['✅ Siguiente paso']], resize_keyboard=True))
    return APOYO

async def recibir_afectados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    if texto in ['Sin Afectados', '➡️ Continuar']:
        await update.message.reply_text("📝 *Detalle del trabajo realizado* (mínimo 15 letras):", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
        return DETALLES
    context.user_data['lista_afectados'].append(texto)
    await update.message.reply_text("✔️ Registrado. ¿Otro? o '➡️ Continuar'", reply_markup=ReplyKeyboardMarkup([['➡️ Continuar']], resize_keyboard=True))
    return AFECTADOS

async def recibir_detalles_y_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    if len(texto.strip()) < 15:
        await update.message.reply_text("⚠️ Informe muy corto. Sea más descriptivo:")
        return DETALLES

    await update.message.reply_text("⏳ Guardando en Google Sheets...")
    
    # Cálculos y Limpieza
    km_s = int(context.user_data.get('km_salida', 0))
    km_l = int(context.user_data.get('km_llegada', 0))
    km_rec = km_l - km_s
    apoyos = "\n".join(context.user_data.get('lista_apoyo', [])) or "Ninguno"
    afectados = "\n".join(context.user_data.get('lista_afectados', [])) or "Ninguno"

    # Fila de 13 Columnas
    fila = [
        context.user_data['fecha'], context.user_data['hora'], context.user_data['unidad'],
        context.user_data['clave'], km_s, context.user_data['ubicacion'], km_l,
        km_rec, context.user_data['personal'], apoyos, afectados, texto, 
        context.user_data['responsable'] # Columna M
    ]

    try:
        sheet.append_row(fila)
        await update.message.reply_text(f"🏁 *¡Parte Guardado!*\nKM Recorridos: {km_rec}\nResponsable: {context.user_data['responsable']}", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Proceso cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            UNIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_unidad)],
            CLAVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_clave)],
            KM_SALIDA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_km_salida)],
            UBICACION: [MessageHandler(filters.LOCATION | filters.TEXT & ~filters.COMMAND, recibir_ubicacion)],
            KM_LLEGADA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_km_llegada)],
            PERSONAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_personal)],
            APOYO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_apoyo)],
            AFECTADOS: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_afectados)],
            DETALLES: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_detalles_y_guardar)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^Cancelar$'), cancel)],
    )
    app.add_handler(conv_handler)
    print("🚒 Sistema en línea con validación de usuarios dinámica.")
    app.run_polling()
