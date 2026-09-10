import os
import json
import uuid
import sys
import threading
import time
import webbrowser
from threading import Timer
from datetime import datetime
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
DB_FILE = 'mancanze.json'
SERVER_CONFIG_FILE = 'server_config.json'

# --- CONFIGURAZIONE SERVER ---
def load_server_config():
    default_config = {"port": 5000, "archive_limit": 100}
    if not os.path.exists(SERVER_CONFIG_FILE):
        return default_config
    try:
        with open(SERVER_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Ensure defaults are present for old files
            if "archive_limit" not in config:
                config["archive_limit"] = 100
            return config
    except Exception as e:
        print(f"Errore lettura config server: {e}")
        return default_config

def save_server_config(data):
    try:
        with open(SERVER_CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"Errore scrittura config server: {e}")
        return False

# --- GESTIONE PERSISTENZA JSON ---
def load_data():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Errore lettura DB: {e}")
        return []

def save_data(data):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Errore scrittura DB: {e}")

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
        if new_limit < 1:
            return jsonify({'error': 'Il limite di archiviazione deve essere positivo'}), 400
    except ValueError:
        return jsonify({'error': 'Porta e Limite devono essere un numero intero'}), 400

    config = load_server_config()
    config['port'] = new_port
    config['archive_limit'] = new_limit
    
    if save_server_config(config):
        return jsonify({'success': True, 'message': 'Configurazione salvata. Riavvia il server per applicare le modifiche.'})
    else:
        return jsonify({'error': 'Errore nel salvataggio'}), 500

@app.route('/api/restart', methods=['POST'])
def restart_server():
    """Riavvia il server."""
    def restart():
        print("Riavvio server tra 1 secondo...")
        time.sleep(1)
        # Riavvia il processo sostituendolo con uno nuovo
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # Avvia il riavvio in un thread separato per permettere il ritorno della risposta HTTP
    threading.Thread(target=restart).start()
    
    return jsonify({'success': True, 'message': 'Riavvio in corso...'})

@app.route('/api/shutdown', methods=['POST'])
def shutdown_server():
    """Spegne il server."""
    def shutdown():
        print("Spegnimento server tra 1 secondo...")
        time.sleep(1)
        os._exit(0) # Terminazione forzata immediata

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
def add_mancanza():
    """Aggiunge una nuova mancanza."""
    req_data = request.get_json()
    if not req_data or 'prodotto' not in req_data:
        return jsonify({'error': 'Dati mancanti'}), 400

    new_item = {
        'id': str(uuid.uuid4()),
        'prodotto': req_data['prodotto'],
        'quantita': req_data.get('quantita', ''),
        'note': req_data.get('note', ''),
        'stato': 'pending',  # pending, ordered
        'timestamp': datetime.now().isoformat()
    }

    data = load_data()
    data.append(new_item)
    save_data(data)
    
    return jsonify(new_item), 201

@app.route('/api/mancanze/<item_id>/ordinato', methods=['POST'])
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
        # Mantieni solo gli ultimi 2000 record
        if len(archivio) > 2000:
            archivio = archivio[-2000:]
        save_archivio(archivio)
        
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Item not found'}), 404

@app.route('/api/mancanze/<item_id>', methods=['DELETE'])
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
ARCHIVIO_FILE = 'archivio.json'

def load_archivio():
    if not os.path.exists(ARCHIVIO_FILE):
        return []
    try:
        with open(ARCHIVIO_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Errore lettura Archivio: {e}")
        return []

def save_archivio(data):
    try:
        with open(ARCHIVIO_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Errore scrittura Archivio: {e}")

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
        # Mantieni solo gli ultimi 2000 record
        if len(archivio) > 2000:
            archivio = archivio[-2000:]
        save_archivio(archivio)
        
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Item not found'}), 404

@app.route('/api/archivio/<item_id>/riordina', methods=['POST'])
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

if __name__ == '__main__':
    # Host 0.0.0.0 rende il server visibile nella LAN
    SERVER_CONFIG = load_server_config()
    PORT = SERVER_CONFIG.get('port', 5000)
    
    def open_browser():
        webbrowser.open_new(f'http://127.0.0.1:{PORT}')

    # Evita di aprire il browser due volte se il reloader è attivo (in sviluppo)
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        Timer(1.5, open_browser).start()

    print("Avvio server Magazzino...")
    print(f"Accessibile via browser all'indirizzo http://<IP_QUESTO_PC>:{PORT}")
    
    # Debug=False è meglio per la produzione/eseguibile
    app.run(host='0.0.0.0', port=PORT, debug=False)
