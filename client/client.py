import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import requests
import json
import os
import re
import sys
import threading
import winsound
import time
from datetime import datetime
import pystray
from PIL import Image, ImageDraw

# --- CONFIGURAZIONE ---
# Come per il server: la configurazione sta accanto all'eseguibile (o nella
# radice del progetto se avviato da sorgente), non nella directory di lavoro.
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# Formato unico per mostrare le date: lo stesso usato per rileggerle quando si
# ordina una colonna. Tenerne uno solo evita che i due si disallineino.
DATE_FMT = "%d/%m/%Y, %H:%M"

def create_normal_icon():
    # Icona Normale (Blu)
    width = 64
    height = 64
    color1 = (52, 152, 219) # Blue
    color2 = (255, 255, 255) # White
    image = Image.new('RGB', (width, height), color1)
    dc = ImageDraw.Draw(image)
    dc.rectangle((width // 2, 0, width, height // 2), fill=color2)
    dc.rectangle((0, height // 2, width // 2, height), fill=color2)
    return image

def create_alert_icon():
    # Icona Allerta (Rossa - Ci sono ordini!)
    width = 64
    height = 64
    color1 = (231, 76, 60) # Red
    color2 = (255, 255, 255) # White
    image = Image.new('RGB', (width, height), color1)
    dc = ImageDraw.Draw(image)
    # Disegna un punto esclamativo stilizzato o pattern diverso
    dc.rectangle((width // 3, 10, 2 * width // 3, 40), fill=color2)
    dc.rectangle((width // 3, 45, 2 * width // 3, 55), fill=color2)
    return image

class MagazzinoClient:
    def __init__(self, root):
        self.root = root
        self.root.title("Notifiche Mancanze Magazzino")
        self.root.geometry("800x500")
        self.root.minsize(700, 400)
        
        self.server_url = ""
        # Intestazione: valore di ripiego finche' non arriva quella del server
        self.titolo = "Articoli Mancanti"
        self.known_ids = set()
        self.first_update_done = False
        self._timer_primo_piano = None
        self.load_config()
        
        # UI Setup
        self.setup_ui()
        self.applica_titolo()
        
        # Tray Icon Setup
        self.tray_icon = None
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        
        # Start Tray in separate thread (dopo aver caricato tutto)
        threading.Thread(target=self.setup_tray, daemon=True).start()

        # Avvio Polling in background
        self.running = True
        self.thread = threading.Thread(target=self.polling_loop, daemon=True)
        self.thread.start()

    def setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Apri", self.restore_from_tray),
            pystray.MenuItem("Esci", self.quit_app)
        )
        self.tray_icon = pystray.Icon("Magazzino", create_normal_icon(), "Magazzino Client", menu)
        self.tray_icon.run()

    def minimize_to_tray(self):
        self.root.withdraw()

    def restore_from_tray(self, icon=None, item=None):
        self.root.after(0, self.restore_window)

    def quit_app(self, icon=None, item=None):
        self.running = False
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    def load_config(self):
        """Carica configurazione o chiede IP all'utente."""
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
            except:
                pass
        
        
        server_ip = config.get("server_ip", "")
        server_port = config.get("server_port", 5000)
        self.archive_limit = config.get("archive_limit", 100)
        
        # Se manca l'IP, chiedilo
        while not server_ip:
            server_ip = simpledialog.askstring("Configurazione", 
                "Inserisci l'IP del PC Magazzino:\n(Usa '127.0.0.1' se stai testando sullo stesso PC)",
                parent=self.root)
            if not server_ip:
                # Se l'utente annulla, chiudiamo o riproviamo? Meglio chiudere.
                if messagebox.askretrycancel("Errore", "IP necessario per continuare."):
                    continue
                else:
                    self.root.destroy()
                    return

        # Salva config
        self.server_url = f"http://{server_ip}:{server_port}"
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"server_ip": server_ip, "server_port": server_port, "archive_limit": self.archive_limit}, f)

    def setup_ui(self):
        # Bottom Frame (Azioni) - Creato PRIMA per garantirne la visibilità in basso
        btn_frame = ttk.Frame(self.root, padding="10")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        btn_refresh = ttk.Button(btn_frame, text="Aggiorna Ora", command=self.refresh_async)
        btn_refresh.pack(side=tk.LEFT, padx=5)
        
        btn_mark = ttk.Button(btn_frame, text="Segna come Ordinato", command=self.mark_as_ordered)
        btn_mark.pack(side=tk.RIGHT, padx=5)

        btn_settings = ttk.Button(btn_frame, text="Impostazioni", command=self.open_settings)
        btn_settings.pack(side=tk.RIGHT, padx=5)

        btn_archive = ttk.Button(btn_frame, text="Archivio", command=self.open_archive)
        btn_archive.pack(side=tk.RIGHT, padx=5)

        # Credits
        lbl_credits = ttk.Label(self.root, text="Software creato da Trentarossi Luca", font=("Segoe UI", 8), foreground="#64748b")
        lbl_credits.pack(side=tk.BOTTOM, pady=2)

        # Frame principale (Tabella) - Prende tutto lo spazio RMANENTE
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Style Configuration for Visibility
        style = ttk.Style()
        
        # Tema che supporta i bordi delle righe/colonne se possibile
        try:
            style.theme_use("clam")
        except: pass
        
        style.configure("Treeview", font=("Segoe UI", 12), rowheight=30, background="#ffffff", foreground="black", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 13, "bold"), background="#f1f5f9")
        
        # Abilita le linee della griglia (dipende dal tema, clam le supporta meglio)
        style.map("Treeview", background=[('selected', '#3498db')])

        # Header (il testo arriva dalle Impostazioni del server)
        self.lbl_title = ttk.Label(main_frame, text=self.titolo, font=("Segoe UI", 18, "bold"))
        self.lbl_title.pack(anchor="w", pady=(0, 15))

        # Treeview (Tabella)
        columns = ("prodotto", "quantita", "note", "ora")
        self.tree = ttk.Treeview(main_frame, columns=columns, show="headings", style="Treeview")
        
        self.tree.heading("prodotto", text="Prodotto")
        self.tree.heading("quantita", text="Qta")
        self.tree.heading("note", text="Note")
        self.tree.heading("ora", text="Ora")
        
        self.tree.column("prodotto", width=250, stretch=tk.YES)
        self.tree.column("quantita", width=80, stretch=tk.NO)
        self.tree.column("note", width=250, stretch=tk.YES)
        self.tree.column("ora", width=160, stretch=tk.NO)
        
        # Tags for zebra striping (colori più decisi)
        self.tree.tag_configure('evenrow', background="#e2e8f0") # Azzurro/grigio più scuro
        self.tree.tag_configure('oddrow', background="#ffffff") # Bianco
        
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Context menu per Copiare
        self.last_clicked_tree = None
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Copia Prodotto (Ctrl+C)", command=lambda: self.copy_selected(self.last_clicked_tree))
        
        self.tree.bind("<Control-c>", lambda e: self.copy_selected(self.tree, e))
        self.tree.bind("<Button-3>", lambda e: self.show_context_menu(e, self.tree))

    def copy_selected(self, tree, event=None):
        if not tree: return
        selected = tree.selection()
        if selected:
            item = tree.item(selected[0])
            if item and 'values' in item and len(item['values']) > 0:
                prodotto = item['values'][0]
                self.root.clipboard_clear()
                self.root.clipboard_append(str(prodotto))
                self.root.update()

    def show_context_menu(self, event, tree):
        iid = tree.identify_row(event.y)
        if iid:
            tree.selection_set(iid)
            self.last_clicked_tree = tree
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def polling_loop(self):
        """Loop infinito per controllare nuovi dati."""
        while self.running:
            try:
                self.refresh_data(notify=True)
            except Exception as e:
                print(f"Errore polling: {e}")
            time.sleep(5) # Controlla ogni 5 secondi

    def refresh_async(self):
        """Aggiornamento manuale in background: la richiesta di rete non deve
        bloccare la finestra mentre attende la risposta del server."""
        threading.Thread(target=self.refresh_data, daemon=True).start()

    def refresh_data(self, notify=False):
        """Scarica i dati dal server e aggiorna la UI."""
        try:
            response = requests.get(f"{self.server_url}/api/mancanze", timeout=3)
            if response.status_code == 200:
                data = response.json()
                # Filtra solo i 'pending' per la visualizzazione attiva, o tutto?
                # Mostriamo solo pending per pulizia
                pending_items = [d for d in data if d.get('stato') == 'pending']
                
                # Aggiorna UI nel thread principale
                self.root.after(0, self.update_table, pending_items, notify)

                # L'intestazione e' definita nelle Impostazioni del server
                self.scarica_titolo()
            else:
                print(f"Server error: {response.status_code}")
        except requests.exceptions.ConnectionError:
            print("Impossibile connettersi al Server (Offline?)")
        except Exception as e:
            print(f"Errore refresh: {e}")

    def scarica_titolo(self):
        """Legge dal server l'intestazione configurata e la applica alla finestra."""
        try:
            risposta = requests.get(f"{self.server_url}/api/settings", timeout=3)
            if risposta.status_code == 200:
                titolo = (risposta.json().get('titolo') or '').strip()
                if titolo and titolo != self.titolo:
                    self.titolo = titolo
                    self.root.after(0, self.applica_titolo)
        except Exception:
            pass  # server non raggiungibile: teniamo l'intestazione attuale

    def applica_titolo(self):
        """Aggiorna intestazione e titolo della finestra (nel thread grafico)."""
        try:
            self.lbl_title.config(text=self.titolo)
            self.root.title(f"{self.titolo} - Magazzino")
        except Exception as e:
            print(f"Errore aggiornamento intestazione: {e}")

    def update_table(self, items, notify):
        # Aggiornamento differenziale invece di svuotare e ricostruire la
        # tabella: la ricostruzione cancellava ogni 5 secondi la riga
        # selezionata dall'utente (e "Segna come Ordinato" rispondeva di non
        # avere nulla da segnare) e riportava la lista in cima.
        selezione = [i for i in self.tree.selection()]
        current_ids = set()
        new_items_found = []

        for posizione, item in enumerate(items):
            item_id = item['id']
            current_ids.add(item_id)

            # Formatta orario
            ts = item.get('timestamp', '')
            try:
                ora_str = datetime.fromisoformat(ts).strftime(DATE_FMT)
            except Exception:
                ora_str = ts

            valori = (item['prodotto'], item['quantita'], item['note'], ora_str)
            tags = ('evenrow',) if posizione % 2 == 0 else ('oddrow',)

            if self.tree.exists(item_id):
                self.tree.item(item_id, values=valori, tags=tags)
                self.tree.move(item_id, '', posizione)
            else:
                self.tree.insert("", posizione, iid=item_id, values=valori, tags=tags)

            # La segnalazione di novita' dipende solo dagli ID gia' notificati,
            # non dal fatto che la riga esista gia' in tabella: un aggiornamento
            # manuale puo' averla inserita senza notificarla.
            if notify and item_id not in self.known_ids:
                new_items_found.append(item['prodotto'])

        # Righe non piu' presenti (ordinate o cancellate altrove)
        for item_id in list(self.tree.get_children("")):
            if item_id not in current_ids:
                self.tree.delete(item_id)

        # Ripristina la selezione sulle righe ancora presenti
        rimaste = [i for i in selezione if self.tree.exists(i)]
        if rimaste:
            self.tree.selection_set(rimaste)

        # Aggiorna Icona Tray
        if self.tray_icon:
            if len(items) > 0:
                self.tray_icon.icon = create_alert_icon()
            else:
                self.tray_icon.icon = create_normal_icon()

        # Aggiorna il set degli ID gia' visti.
        # Con notify=False (aggiornamento manuale, "Segna come ordinato",
        # salvataggio impostazioni) scartiamo solo gli ID spariti: se
        # registrassimo anche quelli nuovi, il controllo automatico successivo
        # li considererebbe gia' noti e la notifica andrebbe persa.
        if notify:
            self.known_ids = current_ids
        else:
            self.known_ids &= current_ids

        # Al primo controllo dopo l'avvio non si segnala nulla: gli articoli
        # gia' in elenco non sono novita' per chi apre il programma adesso.
        if not self.first_update_done:
            self.first_update_done = True
            return

        if new_items_found:
            self.show_notification(new_items_found)

    def show_notification(self, products):
        """Avvisa dell'arrivo di nuovi articoli portando avanti la finestra.

        Non usiamo le notifiche di Windows: sia quelle di plyer sia i "balloon"
        della system tray vengono scartati silenziosamente da Windows 11, quindi
        non comparivano mai. La finestra che si apre davanti a chi lavora e' un
        avviso che non puo' passare inosservato.
        """
        # Breve segnale acustico di sistema
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

        self.restore_window()

    def restore_window(self):
        """Apre la finestra e la porta davanti a tutto, e ce la lascia.

        Windows non permette a un'applicazione in secondo piano di prendersi il
        primo piano: prima il flag "sempre davanti" veniva rilasciato dopo un
        secondo e la finestra ricadeva dietro a quella su cui si stava
        lavorando. Ora resta davanti finche' non la si tocca (o al massimo un
        minuto), cosi' la segnalazione non passa inosservata.
        """
        try:
            self.root.deiconify()      # se ridotta a icona o nascosta nel tray
            self.root.state('normal')
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.focus_force()

            # Un click sulla finestra la riporta al comportamento normale
            self.root.bind("<Button>", self._rilascia_primo_piano, add="+")
            if self._timer_primo_piano is not None:
                self.root.after_cancel(self._timer_primo_piano)
            self._timer_primo_piano = self.root.after(60000, self._rilascia_primo_piano)
        except Exception as e:
            print(f"Errore restore window: {e}")

    def _rilascia_primo_piano(self, event=None):
        """Toglie il "sempre davanti" quando l'utente ha visto la segnalazione."""
        try:
            if self._timer_primo_piano is not None:
                self.root.after_cancel(self._timer_primo_piano)
                self._timer_primo_piano = None
            self.root.unbind("<Button>")
            self.root.attributes('-topmost', False)
        except Exception:
            pass

    def mark_as_ordered(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Seleziona un articolo da segnare come ordinato.")
            return

        for item_id in selected:
            # Chiamata API per aggiornare stato
            threading.Thread(target=self.do_mark_request, args=(item_id,), daemon=True).start()

    def do_mark_request(self, item_id):
        try:
            url = f"{self.server_url}/api/mancanze/{item_id}/ordinato"
            requests.post(url, timeout=5)
            # Al prossimo refresh sparirà
            self.refresh_data(notify=False)
        except Exception as e:
            print(f"Errore update: {e}")
            self.root.after(0, lambda: messagebox.showerror("Errore", "Impossibile aggiornare lo stato"))

    def open_settings(self):
        """Apre finestra per cambiare IP del server."""
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Impostazioni")
        settings_win.geometry("300x320")
        
        # IP
        ttk.Label(settings_win, text="IP Server Magazzino:").pack(pady=(10, 5))
        
        # Estrai IP e Port dall'URL
        # URL format: http://ip:port
        try:
            parts = self.server_url.replace("http://", "").split(":")
            current_ip = parts[0]
            current_port = parts[1] if len(parts) > 1 else "5000"
        except:
            current_ip = ""
            current_port = "5000"
        
        ip_var = tk.StringVar(value=current_ip)
        entry_ip = ttk.Entry(settings_win, textvariable=ip_var, width=30)
        entry_ip.pack(pady=5)

        # Port
        ttk.Label(settings_win, text="Porta Server:").pack(pady=(10, 5))
        port_var = tk.StringVar(value=current_port)
        entry_port = ttk.Entry(settings_win, textvariable=port_var, width=10)
        entry_port.pack(pady=5)
        
        # Limit Archivio
        ttk.Label(settings_win, text="Limite Elementi Archivio:").pack(pady=(10, 5))
        limit_var = tk.StringVar(value=str(self.archive_limit))
        entry_limit = ttk.Entry(settings_win, textvariable=limit_var, width=10)
        entry_limit.pack(pady=5)
        
        def save_settings():
            new_ip = ip_var.get().strip()
            new_port = port_var.get().strip()
            new_limit = limit_var.get().strip()

            if not new_ip:
                messagebox.showerror("Errore", "Inserisci un IP valido", parent=settings_win)
                return
            
            try:
                p = int(new_port)
                if not (1024 <= p <= 65535): raise ValueError()
            except:
                 messagebox.showerror("Errore", "Porta non valida (1024-65535)", parent=settings_win)
                 return
                 
            try:
                l = int(new_limit)
                if l < 1: raise ValueError()
            except:
                 messagebox.showerror("Errore", "Limite non valido (deve essere >= 1)", parent=settings_win)
                 return

            # Salva
            self.server_url = f"http://{new_ip}:{new_port}"
            self.archive_limit = int(new_limit)
            try:
                with open(CONFIG_FILE, 'w') as f:
                    json.dump({"server_ip": new_ip, "server_port": int(new_port), "archive_limit": self.archive_limit}, f)
                messagebox.showinfo("Salvato", "Configurazione aggiornata!", parent=settings_win)
                settings_win.destroy()
                # Prova subito a ricaricare
                self.refresh_data(notify=False)
            except Exception as e:
                messagebox.showerror("Errore", f"Impossibile salvare: {e}", parent=settings_win)

        ttk.Button(settings_win, text="Salva", command=save_settings).pack(pady=20)

    def open_archive(self):
        """Apre finestra con storico archivio."""
        arch_win = tk.Toplevel(self.root)
        arch_win.title("Archivio Storico")
        arch_win.geometry("850x600")
        arch_win.minsize(700, 450)
        
        lbl_info = ttk.Label(arch_win, text=f"Vengono visualizzati gli ultimi {self.archive_limit} record dell'archivio storico.", font=("Segoe UI", 10, "italic"))
        lbl_info.pack(side=tk.TOP, pady=5)
        
        # Frame Ricerca
        search_frame = ttk.Frame(arch_win, padding="5")
        search_frame.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Label(search_frame, text="Cerca Prodotto/Note:").pack(side=tk.LEFT, padx=5)
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, width=40)
        search_entry.pack(side=tk.LEFT, padx=5)
        
        # Tabella Archivio
        columns = ("prodotto", "quantita", "creato", "archiviato")
        tree = ttk.Treeview(arch_win, columns=columns, show="headings")
        
        tree.heading("prodotto", text="Prodotto", command=lambda: self.treeview_sort_column(tree, "prodotto", False))
        tree.heading("quantita", text="Qta", command=lambda: self.treeview_sort_column(tree, "quantita", False))
        tree.heading("creato", text="Inserito il", command=lambda: self.treeview_sort_column(tree, "creato", False))
        tree.heading("archiviato", text="Ordinato il", command=lambda: self.treeview_sort_column(tree, "archiviato", False))
        
        tree.column("prodotto", width=300, stretch=tk.YES)
        tree.column("quantita", width=80, stretch=tk.NO)
        tree.column("creato", width=160, stretch=tk.NO)
        tree.column("archiviato", width=160, stretch=tk.NO)
        
        # Tags for zebra striping (colori più decisi)
        tree.tag_configure('evenrow', background="#e2e8f0")
        tree.tag_configure('oddrow', background="#ffffff")
        
        scrollbar = ttk.Scrollbar(arch_win, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Variabile per il timer di debounce della ricerca
        self.search_timer = None
        
        def nel_thread_grafico(funzione, *args):
            """Esegue nel thread della finestra, ignorando la chiamata se nel
            frattempo l'utente ha chiuso l'archivio."""
            try:
                arch_win.after(0, funzione, *args)
            except tk.TclError:
                pass

        def mostra_errore(messaggio):
            messagebox.showerror("Errore", messaggio, parent=arch_win)

        def riempi_tabella(data):
            """Aggiorna la tabella. Chiamata sempre dal thread grafico."""
            # Ordina per data archiviazione decrescente
            data.sort(key=lambda x: x.get('archived_at', ''), reverse=True)

            for row in tree.get_children():
                tree.delete(row)

            for i, item in enumerate(data):
                # Formatta date
                try:
                    ts_cr = datetime.fromisoformat(item['timestamp']).strftime(DATE_FMT)
                except Exception:
                    ts_cr = item.get('timestamp', '')

                try:
                    ts_ar = datetime.fromisoformat(item['archived_at']).strftime(DATE_FMT)
                except Exception:
                    ts_ar = item.get('archived_at', '')

                tags = ('evenrow',) if i % 2 == 0 else ('oddrow',)
                tree.insert("", "end", values=(
                    item.get('prodotto', ''),
                    item.get('quantita', ''),
                    ts_cr,
                    ts_ar
                ), tags=tags)

        def fetch_and_update_archive_table():
            query = search_var.get().strip()

            if query:
                lbl_info.config(text=f"Ricerca in tutto l'archivio per: '{query}'")
                # I parametri passano da requests, che li codifica: prima una
                # ricerca contenente & o # arrivava troncata o alterata al server.
                params = {'q': query}
            else:
                lbl_info.config(text=f"Vengono visualizzati gli ultimi {self.archive_limit} record dell'archivio storico.")
                params = {'limit': self.archive_limit}

            def scarica():
                try:
                    response = requests.get(f"{self.server_url}/api/archivio",
                                            params=params, timeout=5)
                    if response.status_code == 200:
                        nel_thread_grafico(riempi_tabella, response.json())
                    else:
                        nel_thread_grafico(mostra_errore, "Impossibile caricare archivio")
                except Exception as e:
                    nel_thread_grafico(mostra_errore, f"Errore connessione API: {e}")

            # In background: la ricerca riparte a ogni pausa di digitazione e su
            # un archivio pieno bloccherebbe la finestra a ogni battuta.
            threading.Thread(target=scarica, daemon=True).start()

        def on_search_write(*args):
            if self.search_timer is not None:
                arch_win.after_cancel(self.search_timer)
            # Debounce di 400ms per evitare troppe chiamate API
            self.search_timer = arch_win.after(400, fetch_and_update_archive_table)

        # Inizializza tabella
        fetch_and_update_archive_table()
        
        # Binda la scrittura sul search alla funzione del debounce
        search_var.trace_add("write", on_search_write)
        
        # Bind per Copia nell'archivio
        tree.bind("<Control-c>", lambda e: self.copy_selected(tree, e))
        tree.bind("<Button-3>", lambda e: self.show_context_menu(e, tree))
    def treeview_sort_column(self, tv, col, reverse):
        """Ordina la colonna del Treeview al click."""
        l = [(tv.set(k, col), k) for k in tv.get_children('')]
        
        # Sort logico per date e numeri se possibile, altrimenti stringhe
        try:
            # Prova ordinamento numerico per "quantita" se sono tutti interi validi (o int(x))
            if col == "quantita":
                # La quantita' e' testo libero ("50mt", "2 pacchi", "1,5 kg"):
                # ordiniamo sul numero iniziale, se c'e'.
                def valore_numerico(testo):
                    m = re.match(r"\s*(\d+(?:[.,]\d+)?)", testo or "")
                    return float(m.group(1).replace(',', '.')) if m else 0.0
                l.sort(key=lambda t: valore_numerico(t[0]), reverse=reverse)
            # Ordinamento per date (assumendo il formato DD/MM/YYYY HH:MM)
            elif col in ("creato", "archiviato"):
                def parse_date(date_str):
                    try:
                        return datetime.strptime(date_str, DATE_FMT)
                    except Exception:
                        # Valori vecchi o non riconosciuti finiscono in fondo
                        return datetime.min
                l.sort(key=lambda t: parse_date(t[0]), reverse=reverse)
            else:
                # Fallback al sort alfabetico di default
                l.sort(reverse=reverse)
        except Exception:
            # Fallback generico
            l.sort(reverse=reverse)

        # Riorganizza gli item
        for index, (val, k) in enumerate(l):
            tv.move(k, '', index)

        # Cambia l'ordine al prossimo click
        tv.heading(col, command=lambda: self.treeview_sort_column(tv, col, not reverse))

if __name__ == "__main__":
    root = tk.Tk()
    # Impostiamo icona se presente, altrimenti nulla
    # root.iconbitmap('icon.ico') 
    
    app = MagazzinoClient(root)
    root.mainloop()
