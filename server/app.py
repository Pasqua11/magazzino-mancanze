import os
import json
import uuid
import sys
import shutil
import functools
import threading
import time
import logging
import webbrowser
from logging.handlers import RotatingFileHandler
from threading import Timer
from datetime import datetime
from flask import Flask, request, jsonify, render_template

# L'icona nella barra delle applicazioni e' facoltativa: se le librerie non
# sono disponibili il server funziona ugualmente, semplicemente senza icona.
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_DISPONIBILE = True
except ImportError:
    TRAY_DISPONIBILE = False

# --- PERCORSI ---
# I dati vivono accanto all'eseguibile (build PyInstaller) oppure nella radice
# del progetto (avvio da sorgente), MAI nella directory di lavoro corrente:
# cosi' il server ritrova sempre lo stesso archivio da qualunque punto venga
# avviato (collegamento sul desktop, cartella diversa, avvio automatico).
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    TEMPLATE_DIR = os.path.join(sys._MEIPASS, 'templates')
else:
    _SRC_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.path.dirname(_SRC_DIR)
    TEMPLATE_DIR = os.path.join(_SRC_DIR, 'templates')

app = Flask(__name__, template_folder=TEMPLATE_DIR)

DB_FILE = os.path.join(BASE_DIR, 'mancanze.json')
ARCHIVIO_FILE = os.path.join(BASE_DIR, 'archivio.json')
SERVER_CONFIG_FILE = os.path.join(BASE_DIR, 'server_config.json')

# Numero massimo di record mantenuti nello storico
ARCHIVIO_MAX_RECORD = 2000

# Lunghezze massime accettate dai campi, per evitare che un invio anomalo
# gonfi indefinitamente il file dei dati
MAX_TESTO = 200
MAX_NOTE = 1000

LOG_FILE = os.path.join(BASE_DIR, 'magazzino_server.log')

# --- DIARIO DEGLI EVENTI ---
# L'eseguibile e' compilato senza finestra di console: tutto quello che veniva
# stampato a video andava perso, errori compresi. Ora finisce in un file
# accanto all'eseguibile, consultabile dall'icona nella barra.
log = logging.getLogger('magazzino')

def configura_log():
    formato = logging.Formatter('%(asctime)s  %(levelname)-7s  %(message)s',
                                '%d/%m/%Y %H:%M:%S')
    su_file = RotatingFileHandler(LOG_FILE, maxBytes=512 * 1024,
                                  backupCount=2, encoding='utf-8')
    su_file.setFormatter(formato)

    radice = logging.getLogger()
    radice.setLevel(logging.INFO)
    radice.addHandler(su_file)

    # Avviando da sorgente la console c'e': continuiamo a scrivere anche li'
    if not getattr(sys, 'frozen', False):
        a_video = logging.StreamHandler()
        a_video.setFormatter(formato)
        radice.addHandler(a_video)

    # Il registro delle richieste HTTP e' rumoroso: teniamo solo gli errori
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

# --- GESTIONE PERSISTENZA JSON ---
# I file JSON sono il database dell'applicazione. Flask serve le richieste su
# piu' thread contemporaneamente, quindi ogni ciclo leggi-modifica-riscrivi va
# protetto da un lock: senza, due inserimenti simultanei si sovrascrivono a
# vicenda e una delle due segnalazioni sparisce senza lasciare traccia.
_data_lock = threading.RLock()

def synchronized(fn):
    """Serializza l'intera richiesta: il ciclo leggi-modifica-scrivi diventa atomico."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _data_lock:
            return fn(*args, **kwargs)
    return wrapper

def solo_json(fn):
    """Rifiuta le richieste che non dichiarano un corpo JSON.

    Una pagina web qualunque, aperta per sbaglio da un PC dell'ufficio, puo'
    inviare una POST a questo server tramite un form nascosto, ma non puo'
    dichiarare un corpo JSON senza il consenso esplicito del server. Il
    controllo basta quindi a impedire che un sito esterno spenga il magazzino
    o ne cambi le impostazioni.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not request.is_json:
            return jsonify({'error': 'Richiesta non valida'}), 400
        return fn(*args, **kwargs)
    return wrapper

def testo_valido(valore, massimo):
    """Normalizza un campo di testo in arrivo: stringa, ripulita e troncata."""
    if valore is None:
        return ''
    return str(valore).strip()[:massimo]

def _quarantine(path):
    """Mette da parte un file illeggibile invece di lasciarlo sovrascrivere.

    Senza questo, un JSON troncato veniva letto come lista vuota e la prima
    scrittura successiva cancellava definitivamente i dati recuperabili.
    """
    try:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        dest = f"{path}.corrotto-{stamp}"
        os.replace(path, dest)
        log.warning("File illeggibile messo da parte in: %s", dest)
    except Exception as e:
        log.error("Impossibile mettere da parte %s: %s", path, e)

def _read_json(path, default):
    """Legge un file JSON; se e' danneggiato tenta il recupero dal backup."""
    if not os.path.exists(path):
        return default

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.error("Errore lettura %s: %s", os.path.basename(path), e)

    _quarantine(path)

    backup = path + '.bak'
    if os.path.exists(backup):
        try:
            with open(backup, 'r', encoding='utf-8') as f:
                data = json.load(f)
            log.warning("Dati ripristinati dal backup %s", os.path.basename(backup))
            return data
        except Exception as e:
            log.error("Anche il backup e' illeggibile: %s", e)

    return default

def _write_json(path, data):
    """Scrittura atomica con backup della versione precedente.

    Scrive su un file temporaneo, forza la scrittura fisica su disco e solo
    allora sostituisce l'originale. Un'interruzione a meta' (spegnimento del
    server, crash, black-out) lascia intatto il file precedente invece di
    troncarlo.
    """
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        if os.path.exists(path):
            shutil.copy2(path, path + '.bak')

        os.replace(tmp, path)  # sostituzione atomica
        return True
    except Exception as e:
        log.error("Errore scrittura %s: %s", os.path.basename(path), e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False

# --- CONFIGURAZIONE SERVER ---
def load_server_config():
    default_config = {"port": 5000, "archive_limit": 100}
    config = _read_json(SERVER_CONFIG_FILE, None)
    if not isinstance(config, dict):
        return default_config
    # Completa i valori mancanti nei file di configurazione piu' vecchi
    for chiave, valore in default_config.items():
        config.setdefault(chiave, valore)
    return config

def save_server_config(data):
    return _write_json(SERVER_CONFIG_FILE, data)

# --- DATI ---
def load_data():
    with _data_lock:
        return _read_json(DB_FILE, [])

def save_data(data):
    with _data_lock:
        return _write_json(DB_FILE, data)

def load_archivio():
    with _data_lock:
        return _read_json(ARCHIVIO_FILE, [])

def save_archivio(data):
    with _data_lock:
        return _write_json(ARCHIVIO_FILE, data)

# --- ROUTES & API ---

@app.route('/')
def home():
    """Serve la pagina HTML per l'inserimento."""
    return render_template('index.html')

@app.route('/settings')
def settings_page():
    """Serve la pagina HTML delle impostazioni."""
    return render_template('settings.html')

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Restituisce le impostazioni correnti."""
    return jsonify(load_server_config())

@app.route('/api/settings', methods=['POST'])
@solo_json
@synchronized
def update_settings():
    """Aggiorna le impostazioni."""
    req_data = request.get_json()
    if not req_data or 'port' not in req_data:
        return jsonify({'error': 'Dati mancanti'}), 400
    
    try:
        new_port = int(req_data['port'])
        if not (1024 <= new_port <= 65535):
             return jsonify({'error': 'Porta non valida (usa 1024-65535)'}), 400
        
        new_limit = int(req_data.get('archive_limit', 100))
        if not (1 <= new_limit <= ARCHIVIO_MAX_RECORD):
            return jsonify({'error': f'Il limite deve essere tra 1 e {ARCHIVIO_MAX_RECORD}'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Porta e Limite devono essere un numero intero'}), 400

    config = load_server_config()
    config['port'] = new_port
    config['archive_limit'] = new_limit
    
    if save_server_config(config):
        return jsonify({'success': True, 'message': 'Configurazione salvata. Riavvia il server per applicare le modifiche.'})
    else:
        return jsonify({'error': 'Errore nel salvataggio'}), 500

@app.route('/api/restart', methods=['POST'])
@solo_json
def restart_server():
    """Riavvia il server."""
    def restart():
        log.info("Riavvio del server richiesto")
        time.sleep(1)
        # Riavvia il processo sostituendolo con uno nuovo
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # Avvia il riavvio in un thread separato per permettere il ritorno della risposta HTTP
    threading.Thread(target=restart).start()
    
    return jsonify({'success': True, 'message': 'Riavvio in corso...'})

@app.route('/api/shutdown', methods=['POST'])
@solo_json
def shutdown_server():
    """Spegne il server."""
    def shutdown():
        log.info("Spegnimento del server richiesto")
        time.sleep(1)
        # Attende che l'eventuale scrittura in corso sia conclusa, altrimenti
        # la terminazione forzata puo' lasciare un JSON a meta'
        with _data_lock:
            os._exit(0)

    threading.Thread(target=shutdown).start()
    return jsonify({'success': True, 'message': 'Spegnimento in corso...'})

@app.route('/api/mancanze', methods=['GET'])
def get_mancanze():
    """Restituisce la lista di tutte le mancanze (escluse quelle archiviate/cancellate se si volesse estendere)."""
    data = load_data()
    # Filtriamo opzionalmente solo quelle non completate se volessimo
    # Per ora restituiamo tutto, il client filtrerà quelle "pending"
    return jsonify(data)

@app.route('/api/mancanze', methods=['POST'])
@synchronized
def add_mancanza():
    """Aggiunge una nuova mancanza."""
    req_data = request.get_json(silent=True)
    if not req_data:
        return jsonify({'error': 'Dati mancanti'}), 400

    # Il campo obbligatorio del modulo si aggira facilmente chiamando l'API
    # direttamente: senza questo controllo finivano in elenco righe vuote.
    prodotto = testo_valido(req_data.get('prodotto'), MAX_TESTO)
    if not prodotto:
        return jsonify({'error': "Il nome del prodotto e' obbligatorio"}), 400

    new_item = {
        'id': str(uuid.uuid4()),
        'prodotto': prodotto,
        'quantita': testo_valido(req_data.get('quantita'), MAX_TESTO),
        'note': testo_valido(req_data.get('note'), MAX_NOTE),
        'stato': 'pending',  # pending, ordered
        'timestamp': datetime.now().isoformat()
    }

    data = load_data()
    data.append(new_item)
    save_data(data)
    
    return jsonify(new_item), 201

@app.route('/api/mancanze/<item_id>/ordinato', methods=['POST'])
@synchronized
def mark_ordered(item_id):
    """Segna come ordinato E SPOSTA IN ARCHIVIO AUTOMATICAMENTE."""
    data = load_data()
    item_to_archive = None
    
    new_data = []
    found = False
    
    for item in data:
        if item['id'] == item_id:
            item['stato'] = 'ordered' # Imposta stato
            item['archived_at'] = datetime.now().isoformat() # Timestamp archivio
            item_to_archive = item
            found = True
        else:
            new_data.append(item)
    
    if found and item_to_archive:
        # Salva lista principale aggiornata (senza l'item)
        save_data(new_data)
        
        # Salva in archivio
        archivio = load_archivio()
        archivio.append(item_to_archive)
        # Mantieni solo i record piu' recenti
        if len(archivio) > ARCHIVIO_MAX_RECORD:
            archivio = archivio[-ARCHIVIO_MAX_RECORD:]
        save_archivio(archivio)
        
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Item not found'}), 404

@app.route('/api/mancanze/<item_id>', methods=['DELETE'])
@synchronized
def delete_mancanza(item_id):
    """Cancella una mancanza."""
    data = load_data()
    initial_len = len(data)
    data = [item for item in data if item['id'] != item_id]
    
    if len(data) < initial_len:
        save_data(data)
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Item not found'}), 404



# --- ARCHIVIO ---

@app.route('/archivio')
def view_archivio():
    """Serve la pagina HTML dell'archivio."""
    config = load_server_config()
    limit = config.get('archive_limit', 100)
    return render_template('archivio.html', archive_limit=limit)

@app.route('/api/archivio', methods=['GET'])
def get_archivio():
    """Restituisce tutto l'archivio logicamente ordinato, opzionalmente limitato e filtrato."""
    data = load_archivio()
    query = request.args.get('q', '').lower()
    
    if query:
        filtered_data = []
        for item in data:
            prodotto = item.get('prodotto', '').lower()
            note = item.get('note', '').lower()
            if query in prodotto or query in note:
                filtered_data.append(item)
        data = filtered_data
        # Ignoriamo il limite se c'è una query esplicita per permettere di cercare in tutto l'archivio
        return jsonify(data)
        
    limit = request.args.get('limit', type=int)
    if limit is not None and limit > 0:
        return jsonify(data[-limit:])
    return jsonify(data)

@app.route('/api/mancanze/<item_id>/archivia', methods=['POST'])
@synchronized
def archive_mancanza(item_id):
    """Sposta una mancanza in archivio."""
    data = load_data()
    item_to_archive = None
    
    # Trova e rimuovi dalla lista principale
    new_data = []
    for item in data:
        if item['id'] == item_id:
            item_to_archive = item
        else:
            new_data.append(item)
    
    if item_to_archive:
        save_data(new_data)
        
        # Aggiungi meta-dati archiviazione
        item_to_archive['archived_at'] = datetime.now().isoformat()
        
        # Salva in archivio
        archivio = load_archivio()
        archivio.append(item_to_archive)
        # Mantieni solo i record piu' recenti
        if len(archivio) > ARCHIVIO_MAX_RECORD:
            archivio = archivio[-ARCHIVIO_MAX_RECORD:]
        save_archivio(archivio)
        
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Item not found'}), 404

@app.route('/api/archivio/<item_id>/riordina', methods=['POST'])
@synchronized
def riordina_mancanza(item_id):
    """Riordina un articolo dall'archivio (crea nuova mancanza)."""
    archivio = load_archivio()
    item_to_reorder = None
    
    for item in archivio:
        if item['id'] == item_id:
            item_to_reorder = item
            break
            
    if item_to_reorder:
        # Crea nuovo item basato sul vecchio
        new_item = {
            'id': str(uuid.uuid4()),
            'prodotto': item_to_reorder['prodotto'],
            'quantita': item_to_reorder.get('quantita', ''),
            'note': item_to_reorder.get('note', ''),
            'stato': 'pending',
            'timestamp': datetime.now().isoformat()
        }
        
        # Salva in lista principale
        data = load_data()
        data.append(new_item)
        save_data(data)
        
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Item not found'}), 404

# --- ICONA NELLA BARRA DELLE APPLICAZIONI ---
# L'eseguibile e' compilato senza console: senza icona, una volta avviato il
# server non e' ne' visibile ne' chiudibile se non dal Gestione attivita'.

def crea_icona_immagine():
    """Disegna l'icona: uno scaffale stilizzato su fondo verde."""
    lato = 64
    immagine = Image.new('RGB', (lato, lato), (22, 101, 52))
    disegno = ImageDraw.Draw(immagine)
    bianco = (255, 255, 255)
    disegno.rectangle((12, 14, 52, 50), outline=bianco, width=4)
    disegno.line((12, 32, 52, 32), fill=bianco, width=4)
    disegno.line((32, 32, 32, 50), fill=bianco, width=4)
    return immagine

def apri_con_windows(percorso):
    """Apre un file o una cartella con l'applicazione predefinita."""
    try:
        if hasattr(os, 'startfile'):
            os.startfile(percorso)
        else:
            webbrowser.open(f'file://{percorso}')
    except Exception as e:
        log.error("Impossibile aprire %s: %s", percorso, e)

def costruisci_icona(porta):
    def apri_pagina(icona=None, voce=None):
        webbrowser.open_new(f'http://127.0.0.1:{porta}')

    def apri_cartella_dati(icona=None, voce=None):
        apri_con_windows(BASE_DIR)

    def apri_diario(icona=None, voce=None):
        apri_con_windows(LOG_FILE)

    def spegni(icona=None, voce=None):
        log.info("Spegnimento richiesto dall'icona nella barra")
        icona.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Apri pagina magazzino", apri_pagina, default=True),
        pystray.MenuItem("Apri cartella dati", apri_cartella_dati),
        pystray.MenuItem("Mostra diario eventi", apri_diario),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Spegni server", spegni),
    )
    return pystray.Icon("MagazzinoServer", crea_icona_immagine(),
                        f"Server Magazzino - porta {porta}", menu)

if __name__ == '__main__':
    configura_log()

    SERVER_CONFIG = load_server_config()
    PORT = SERVER_CONFIG.get('port', 5000)

    def open_browser():
        webbrowser.open_new(f'http://127.0.0.1:{PORT}')

    def avvia_server_web():
        # Host 0.0.0.0 rende il server visibile nella LAN
        try:
            app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
        except Exception as e:
            log.critical("Il server web si e' fermato: %s", e)

    log.info("Avvio server Magazzino sulla porta %s", PORT)
    log.info("Accessibile dalla rete all'indirizzo http://<IP_QUESTO_PC>:%s", PORT)
    log.info("Cartella dati: %s", BASE_DIR)

    Timer(1.5, open_browser).start()

    if TRAY_DISPONIBILE:
        # Il server web va in un thread non-daemon: anche se l'icona non
        # dovesse partire, il processo resta vivo e continua a servire i client.
        threading.Thread(target=avvia_server_web, name='server-web',
                         daemon=False).start()
        try:
            costruisci_icona(PORT).run()  # blocca fino a "Spegni server"
        except Exception as e:
            log.error("Icona nella barra non disponibile: %s", e)
        else:
            log.info("Server chiuso dall'utente")
            with _data_lock:  # non interrompere una scrittura in corso
                os._exit(0)
    else:
        avvia_server_web()
