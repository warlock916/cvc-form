# CVC – Valutazione Formazione Istruttori

Sistema web per la valutazione degli allievi nei corsi CVC:
- **ADV** (Valutazione Conclusiva + Operativo)
- **Istruttori** (Valutazione Conclusiva + Operativo)
- **Istruttori C3** (Valutazione Conclusiva)

## Funzionalità
- 👤 Gestione allievi con foto
- 📝 Blocco note per ogni allievo
- 🚦 Semafori automatici per sezione
- 📊 Calcolo punteggio totale con soglia promozione
- 💾 Salvataggio automatico nel browser (localStorage)
- 📥 Esportazione CSV

## Deploy su Railway

1. **Push su GitHub** nel repository `cvc-form`
2. Su [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Seleziona il repository `cvc-form`
4. Railway rileva automaticamente Node.js e usa `npm start`
5. Il sito sarà live su un URL `.railway.app`

## Sviluppo locale

```bash
npm install
npm start
# apri http://localhost:3000
```

## Struttura

```
cvc-form/
├── index.html    # App completa single-file
├── server.js     # Express server per Railway
├── package.json
└── README.md
```
