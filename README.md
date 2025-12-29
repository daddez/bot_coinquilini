## 🤔 Perché questo bot?

**Gestire le pulizie è sempre un caos?**
Con **Alibhi** 🧹 non lo sarà più: assegna automaticamente i turni, invia promemoria e tiene traccia di chi ha fatto cosa, senza discussioni.

**Vi dimenticate sempre chi deve pulire il bagno?**
Alibhi lo ricorda per voi ⏰, inviando notifiche mirate solo al coinquilino responsabile.

**Le pulizie finiscono sempre per far litigare qualcuno?**
Con conferme chiare tramite bottoni ✅, tutto è tracciato e trasparente, così nessuno può dire “non toccava a me”.

**Tenere traccia delle spese comuni è complicato?**
Con Alibhi 💰 basta inserire l’importo e la ricevuta: la contabilità si aggiorna da sola.

**Non vi ricordate mai chi ha pagato l’ultima spesa?**
Alibhi registra ogni acquisto 📊, così puoi controllare tutto in qualsiasi momento.

**Le ricevute finiscono sempre perse o dimenticate?**
Con Alibhi 🧾 ogni ricevuta viene salvata e organizzata nella WebApp, sempre a portata di mano.

**Fare la lista della spesa su mille chat diverse è frustrante?**
Con Alibhi 🛒 c’è un’unica lista condivisa, sempre aggiornata e accessibile a tutti.

**Capita di comprare due volte la stessa cosa?**
Alibhi mostra cosa è già stato acquistato ✔️, evitando sprechi e doppioni.

**Ti scoccia dover ricordare agli altri cosa devono fare?**
Lascia fare ad Alibhi 🤖: manda lui i promemoria, così tu non passi per quello “rompiscatole”.

**Vuoi controllare spese e ricevute senza aprire Telegram?**
Con la WebApp 🌐 puoi visualizzare tutto da browser, in modo semplice e ordinato.

**Hai paura che chiunque possa accedere ai vostri dati?**
Alibhi protegge tutto con token sicuri 🔐 e sessioni a tempo limitato.

**Vivere in casa condivisa ti sembra sempre più complicato del dovuto?**
Con Alibhi 🏠 automatizzi spese e pulizie, riducendo stress, confusione e discussioni.

---

## 🏠 1. Introduzione

**“Alibhi”** 🤖 è un bot Telegram progettato per aiutare **gruppi di coinquilini** nella gestione condivisa di:

* 💰 **Spese**
* 🧹 **Pulizie**
* 📊 **Contabilità domestica**

Il bot include anche una **WebApp integrata** 🌐 per la visualizzazione e la gestione delle **ricevute** e delle **spese**, rendendo tutto più semplice e trasparente.

## 🧱 2. Architettura Generale

Il sistema è composto da:

* 🤖 **Bot Telegram** (basato su `python-telegram-bot`)
* 🚀 **Backend FastAPI** per la WebApp
* 🗄️ **Database** (SQLite o PostgreSQL) per la persistenza dei dati
* 🧩 **Moduli separati** per:

  * logica bot
  * web
  * database
  * modelli
  * tastiere
  * utility

👉 Il **bot** e la **WebApp** vengono eseguiti insieme:

* il bot gira in un **thread separato**
* FastAPI gestisce le **richieste web**

## ⚙️ 3. Funzionalità Principali
  
  ### 🛒 3.1 Gestione della Spesa
  
  * ➕ Gli utenti possono **aggiungere prodotti** da acquistare tramite il bot
  * 📋 È possibile **visualizzare la lista della spesa**
  * ✅ I prodotti possono essere **segnati come acquistati**
  * 🧾 Dopo l’acquisto, l’utente invia:
  
  * l’**importo speso**
  * la **foto della ricevuta**
  * 📈 Il bot registra la transazione e aggiorna la **contabilità**
  
  ### 🧹 3.2 Gestione delle Pulizie
  
  * ⏰ Il bot invia **promemoria giornalieri** per le pulizie
  * 👥 Le aree vengono **assegnate ai coinquilini**
  * 🔘 Gli utenti confermano la pulizia tramite **bottoni interattivi**
  * ⚙️ Aree e turni sono **completamente configurabili**
  
  ### 🧾 3.3 Gestione Ricevute e Contabilità
  
  * 📸 Ogni spesa è associata a una **ricevuta** (foto o screenshot)
  * 🌐 Le ricevute sono accessibili tramite la **WebApp**
  * 🖼️ Visualizzazione con **carosello immagini** e dettagli
  * 📊 Possibilità di generare:
      * estratti conto
      * riepiloghi delle spese
  
  ### 🌐 3.4 WebApp Integrata
  
  * 🔐 Accesso tramite **link generato dal bot** (token sicuro per sessione)
  * 🛍️ Visualizzazione:  
      * lista della spesa
      * ricevute
  * 📱 Interfaccia **moderna e responsiva**

## 🔄 4. Flusso di Utilizzo Step by Step

### ➕ 4.1 Aggiunta di una Spesa

1. L’utente seleziona **“Aggiungi spesa”** dal bot
2. Inserisce il **nome del prodotto** (o più prodotti)
3. Dopo l’acquisto, indica l’**importo speso**
4. Il bot richiede la **foto della ricevuta**
5. La spesa viene **registrata** e la ricevuta **salvata**

### 🧹 4.2 Gestione Pulizie

1. Il bot invia un **promemoria** all’utente responsabile
2. L’utente conferma la pulizia tramite **bottone**
3. Il sistema aggiorna lo **stato** e passa al **prossimo turno**

### 🌐 4.3 Accesso alla WebApp

1. L’utente riceve un **link dal bot**
2. Accede alla WebApp per visualizzare:
   * lista della spesa
   * ricevute
   * riepiloghi
3. 🔒 Le sessioni web hanno **durata limitata** per sicurezza

## 🧩 5. Componenti Tecniche e Struttura del Codice

* **`main.py`** ▶️ Avvio del sistema (bot + WebApp)
* **`alibhi/bot/`** 🤖 Logica del bot Telegram
* **`alibhi/web/`** 🌐 Backend FastAPI e rotte WebApp
* **`alibhi/models.py`** 📦 Modelli dati (utenti, prodotti, transazioni, sessioni)
* **`alibhi/db.py`** 🗄️ Gestione database e migrazioni
* **`alibhi/keyboards.py`** ⌨️ Tastiere interattive Telegram
* **`alibhi/utils.py`** 🛠️ Utility (formattazione, validazione, token)
* **`alibhi/schemas.py`** 🧠 Strutture dati thread-safe
* **`alibhi/tasks.py`** ⏱️ Task periodici (promemoria, pulizia sessioni)

## 🔐 6. Sicurezza e Configurazione

* 🔑 Dati sensibili gestiti tramite:
    * variabili d’ambiente
    * file `.env`
* 🕒 Sessioni web protette da **token univoci** con **scadenza automatica**
* 🗄️ Dati salvati in un database **sicuro e persistente**

## ✅ 7. Conclusioni

**“Alibhi”** semplifica e automatizza la gestione di **spese** e **pulizie** in una casa condivisa 🏡.
Grazie all’integrazione tra **Telegram** e **Web**, il sistema risulta:

* 🧩 **Modulare**
* 🔐 **Sicuro**
* 🚀 **Facilmente estendibile**

Perfetto per rendere la convivenza più organizzata e senza stress 😄

---

## 📖 Istruzioni per Avviare il Bot Telegram "Alibhi"

## 1. Prerequisiti
- **Python 3.10+** installato sul sistema
- **PostgreSQL** installato e in esecuzione 
- **Git** (opzionale, per clonare il repository)
- **Account t.ly** (opzionale, ma consigliato)
- Un **token Telegram Bot** (creato tramite BotFather)

## 2. Clona o scarica il progetto
Se non l’hai già fatto:
```sh
git clone https://github.com/daddez/bot_coinquilini.git
cd alibhi-bot
```
Oppure scarica e decomprimi la cartella.

## 3. Crea e configura l’ambiente Python
Si consiglia l’uso di un ambiente virtuale:
```sh
python -m venv venv
venv\Scripts\activate  # Su Windows
# oppure
source venv/bin/activate  # Su Linux/Mac
```

## 4. Installa le dipendenze
```sh
pip install -r requirements.txt
```

## 5. Configura il file `.env`
Compila il file `.env` nella root del progetto con:
- `BOT_TOKEN`: il token del tuo bot Telegram
- `BASE_URL`: l’URL pubblico dove sarà accessibile la webapp (es. https://tuosito.com)
- `SHOP_SECRET`: una stringa lunga e casuale (puoi generarla con un generatore di password)
- `DATABASE_URL`: stringa di connessione al database (es. per PostgreSQL: `postgresql+psycopg2://user:pass@localhost:5432/alibhi`)
- `RECEIPTS_DIR`: cartella dove salvare le ricevute (es. `receipts`)
- `TLY_TOKEN`: opzionale, per accorciare i link

## 6. Prepara il database
Assicurati che il database esista e sia accessibile. Se usi PostgreSQL:
- Crea il database e l’utente:
```sh
psql -U postgres
CREATE DATABASE alibhi;
CREATE USER alibhi WITH PASSWORD 'alibhi';
GRANT ALL PRIVILEGES ON DATABASE alibhi TO alibhi;
```
- Modifica la stringa `DATABASE_URL` nel `.env` se necessario.

## 7. Avvia il bot e la webapp
Dalla root del progetto:
```sh
python main.py
```
Questo comando avvia sia il bot Telegram che la webapp (FastAPI/Uvicorn). Il bot inizierà a rispondere ai messaggi e la webapp sarà accessibile all’indirizzo specificato in `BASE_URL` (di default su http://localhost:8080).

## 8. Prova il bot
- Cerca il tuo bot su Telegram e avvia una chat.
- Usa i comandi disponibili (es. /start, aggiungi spesa, ecc.).
- Prova a generare un link per la webapp e accedi dal browser.

## 9. (Opzionale) Deploy su server
Per uso pubblico:
- Usa un server (VPS, cloud, ecc.) con Python e PostgreSQL.
- Punta il DNS del dominio su questo server.
- Configura un reverse proxy (es. Nginx) per servire la webapp su HTTPS.
- Mantieni il processo attivo con `systemd`, `pm2`, `supervisor` o simili.

## 10. Risoluzione problemi
- Verifica che tutte le variabili nel `.env` siano corrette.
- Controlla i log in console per eventuali errori.
- Assicurati che il database sia raggiungibile.
- Se il bot non risponde, verifica il token e la connessione internet.

---

