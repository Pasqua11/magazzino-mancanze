# Sistema Mancanze Magazzino - Guida all'Uso

Questo sistema permette di segnalare mancanze dal magazzino (Server) e ricevere notifiche in tempo reale in ufficio (Client).

## 1. Installazione
Assicurati di avere Python installato su entrambi i PC.
### Lato Server
1.  Aprire un terminale o prompt dei comandi.
2.  Navigare nella cartella del server.
3.  Eseguire il file `ServerMagazzino.exe` (La porta di default è `5000` ma può essere cambiata nelle Impostazioni web).
4.  Il server rimarrà in ascolto e gestirà le segnalazioni.
5.  Compare un'**icona verde nella barra delle applicazioni**, in basso a destra.
    Con il tasto destro si apre il menu: pagina del magazzino, cartella dei dati,
    diario degli eventi e spegnimento del server. Doppio click apre la pagina.

Se qualcosa non funziona, il file `magazzino_server.log` accanto all'eseguibile
riporta errori e avvii: è la prima cosa da guardare.

### Lato Client
1.  Aprire un terminale o prompt dei comandi.
2.  Navigare nella cartella del client.
3.  Eseguire il file `ClientMagazzino.exe`.
4.  Al primo avvio, inserire l'indirizzo IP del computer su cui è in esecuzione il server (es. `192.168.1.50`).

---

## 🚀 Nuove Funzionalità Introdotte
*   **Impostazioni e Limite Archivio Dinamici:** Sia il Server (nella pagina Impostazioni) sia il Client (cliccando sul pulsante dedicato in basso a destra) permettono ora all'utente di definire un limite massimo di caricamento righe personalizzato (es. ultimi 100 record) per rendere l'avvio delle tabelle di Storico fulmineo senza sovraccaricare il database JSON.
*   **Archiviazione con Auto-Troncamento (Max 2000 Record):** Il Server tiene traccia di tutte le aggiunte nel database `archivio.json`. Per mantenere in salute le prestazioni del JSON evitando crash futuri, i file più antichi verranno scartati non appena si proveranno ad accumulare più di *2000* righe storiche in assoluto in totale.
*   **Ricerca Globale nell'Archivio Server-Side:** La casella "Cerca Articolo/Descrizione" in cima all'archivio (sia sull'app PC Client che sul Web Server) interroga in tempo reale **intero pacchetto storico** di dati, eludendo il summenzionato limite visuale.
*   **Ordinamento Colonne Bidirezionale:** Nel database Client e Web cliccare in cima alle colonne (ex. "Quantità") per ordinare a piacere la classifica visiva (crescente ▼ o decrescente ▲).
*   **Compattezza Ora (HH:MM):** Tagliati via inutili e scomodi display dei secondi. Le date si posano pulite negli spazi. Setup a righe alternate (Zebra Striping bianche-azzurrine) aggiunto per massimizzare la leggibilità per righe.
*   **Appunti (Clipboard) Rapidi:** È in ogni momento possibile copiare testualmente la voce intera del Prodotto con il tasto `CTRL+C` nelle tabelle client, o con apposito click destro.

**Per Test Locale (stesso PC):**
Vai su `http://localhost:5000` nel browser.

## 3. Avvio del CLIENT (PC Ufficio)
1. Fai doppio click su `AVVIA_CLIENT.bat`.
2. Al primo avvio, ti chiederà l'IP del Server.
   - **Se sei in LAN reale**: Inserisci l'IP del PC Magazzino (es. `192.168.1.50`).
   - **Se stai testando sullo stesso PC**: Inserisci `127.0.0.1` o `localhost`.
3. Il programma si aprirà e controllerà le mancanze ogni 5 secondi.
4. Quando il Magazzino inserisce un nuovo articolo, riceverai una **Notifica Windows** (in basso a destra).

## 4. Reset Configurazione
Se sbagli a inserire l'IP, cancella il file `config.json` e riavvia il Client.
Il file si trova accanto a `ClientMagazzino.exe` (o nella cartella del progetto se avvii da sorgente).

## 5. Struttura File
- `server/app.py`: Logica Server.
- `client/client.py`: Applicazione Desktop.

I dati vengono creati accanto all'eseguibile del Server (o nella cartella del progetto
se avviato da sorgente), indipendentemente da dove venga lanciato:
- `mancanze.json`: articoli mancanti in attesa.
- `archivio.json`: storico degli articoli ordinati (max 2000 record).
- `server_config.json` / `config.json`: impostazioni di Server e Client.
