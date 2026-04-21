from flask import Flask, request, jsonify, send_from_directory, Response, send_file
from flask_cors import CORS
import os, secrets, functools, csv, io, hashlib, json, base64
from datetime import date
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
CORS(app)

ADMIN_PWD    = os.environ.get('ADMIN_PASSWORD', 'admin123')
FOTO_PWD     = os.environ.get('FOTO_PASSWORD', 'titta01')
DATABASE_URL = os.environ.get('DATABASE_URL', '')
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/tmp/uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── Database setup ────────────────────────────────────────────────────────────
# Supporta sia PostgreSQL (Railway) che SQLite (locale/fallback)
# Railway fornisce DATABASE_URL come "postgresql://..." o "postgres://..."

USE_PG = False
PH = '?'

if DATABASE_URL:
    try:
        import psycopg2
        import psycopg2.extras
        # Railway usa sia "postgres://" che "postgresql://"
        _db_url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

        def get_db():
            conn = psycopg2.connect(_db_url, sslmode='require')
            return conn

        # Test connessione
        _test = get_db()
        _test.close()
        USE_PG = True
        PH = '%s'
        print(f"[DB] PostgreSQL connesso OK")
    except Exception as e:
        print(f"[DB] PostgreSQL fallito ({e}), uso SQLite")
        USE_PG = False

if not USE_PG:
    import sqlite3
    DB = os.environ.get('DB_PATH', 'cvc_istruttori.db')
    def get_db():
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        return conn
    PH = '?'
    print(f"[DB] SQLite: {DB}")

def rows_to_dicts(rows, cursor=None):
    if not rows: return []
    if USE_PG:
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    return [dict(r) for r in rows]

def row_to_dict(row, cursor=None):
    if row is None: return None
    if USE_PG:
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    return dict(row)

def hash_pwd(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def get_field(row, idx, name):
    """Accede a un campo di una riga in modo compatibile PG/SQLite."""
    if row is None: return None
    return row[idx] if USE_PG else row[name]

# ── Corsi disponibili ────────────────────────────────────────────────────────
CORSI_VALIDI = ['ADV', 'Istruttori1', 'IstruttoriC3']

# ── Schema valutazioni per corso ─────────────────────────────────────────────
# Ogni sezione ha: macro (titolo), items (lista dict con peso e desc)
# Per fogli operativi: items è lista di stringhe (senza peso)

SCHEMA_ADV = [
    {'macro': '1. Navigazione a vela', 'items': [
        {'peso': 2, 'desc': "È in grado di condurre con buona sicurezza e autonomia sia una deriva che un cabinato"},
        {'peso': 3, 'desc': "È in grado di eseguire le manovre fondamentali (gavitello, ancoraggio, regolazione e cambio velatura)"},
        {'peso': 3, 'desc': "È in grado di eseguire le manovre fondamentali con metodo e consapevolezza (SN+VI)"},
    ]},
    {'macro': '2. Mezzi e procedure di sicurezza', 'items': [
        {'peso': 2, 'desc': "È in grado di preparare i mezzi di sicurezza e gestire motore nel rispetto delle norme ambientali"},
        {'peso': 3, 'desc': "È in grado di collaborare con l'istruttore durante le manovre di sicurezza"},
        {'peso': 3, 'desc': "Si comporta coerentemente alle procedure di sicurezza, in mare e a terra"},
    ]},
    {'macro': '3. Didattica alla lavagna e in mare', 'items': [
        {'peso': 2, 'desc': "È in grado di comprendere le indicazioni didattiche del CT e fare da facilitatore agli allievi"},
    ]},
    {'macro': '4. Capacità gestionale e lavoro in team', 'items': [
        {'peso': 2, 'desc': "È in grado di supportare il gruppo istruttori sia a terra che in mare"},
        {'peso': 2, 'desc': "È disponibile ad accrescere la propria esperienza collaborando con il team istruttori AdV"},
        {'peso': 1, 'desc': "Condivide e promuove le norme di comportamento (carta dei valori, inclusione, sostenibilità)"},
    ]},
    {'macro': '5. Consapevolezza del ruolo – Motivazione Impegno Disponibilità', 'items': [
        {'peso': 2, 'desc': "È consapevole di essere modello di riferimento a terra e a mare"},
        {'peso': 2, 'desc': "È in grado di mantenere la calma in situazioni di stress, sostiene e incoraggia gli altri"},
        {'peso': 2, 'desc': "È sempre un elemento proattivo, non si tira indietro o delega ad altri"},
    ]},
    {'macro': '6. Capacità organizzative e aspetti logistici', 'items': [
        {'peso': 2, 'desc': "È in grado di supportare e facilitare le attività a mare (scalo, caletta, veleria) e a terra"},
        {'peso': 1, 'desc': "È in grado di prevenire e risolvere piccole avarie coordinandosi con CT e staff"},
        {'peso': 1, 'desc': "Conosce le procedure di prevenzione ed emergenza a terra e a mare"},
    ]},
]

SCHEMA_IS1 = [
    {'macro': '1. Navigazione a vela', 'items': [
        {'peso': 2, 'desc': "E' in grado di condurre con buona sicurezza e autonomia sia una deriva che un cabinato.(T) E' in grado di valutare e navigare nelle zone piu sicure, rispettando i perimetri di navigazione(SN)"},
        {'peso': 3, 'desc': "E' in grado di eseguire costantemente tutte le manovre fondamentali (tra cui gavitello, ancoraggio, quickstop), con regolazioni e velatura adeguata, con una buona visione a 360, garantendo la totale sicurezza dell'imbarcazione e dell'equipaggio."},
        {'peso': 3, 'desc': "E' in grado di eseguire tutte manovre fondamentali, in ogni condizione, con metodo e cognizione di causa, avendo sempre in chiaro via di fuga e obbiettivo esercizio (SN+VI)"},
    ]},
    {'macro': '2. Mezzi e procedure di sicurezza', 'items': [
        {'peso': 2, 'desc': "E' in grado di condurre ed eseguire le manovre base (accosti e rotazione 360 oraria) in autonomia e sufficiente sicurezza sia con il gozzo che gommone"},
        {'peso': 3, 'desc': "E' in grado di impostare una manovra di avvicinamento e relativa manovra di assistenza con metodo e cognizione di causa. Ha sempre in chiaro la via di fuga."},
        {'peso': 3, 'desc': "E' in grado di mantenere il controllo del mezzo senza diventare pericoloso per se e per gli assistiti"},
    ]},
    {'macro': '3. Didattica alla lavagna e in mare', 'items': [
        {'peso': 3, 'desc': "E' in grado di organizzare i contenuti di un argomento del corso, avendone sufficiente conoscenza per individuarne i punti chiave"},
        {'peso': 3, 'desc': "E' in grado di comunicare con sufficiente efficacia i punti chiave di quel argomento (chiarezza espositiva), gestendo lo spazio della lavagna con parole disegni chiari e ordinati e con la terminologia e gergo nautico corretto"},
        {'peso': 1, 'desc': "E' in grado di valutare se l'obiettivo didattico e' stato raggiunto"},
    ]},
    {'macro': '4. Capacita gestionale e team - Organizzazione e Comunicazione', 'items': [
        {'peso': 2, 'desc': "E' in grado di lavorare in team per raggiungimento obbiettivo comune"},
        {'peso': 2, 'desc': "E' in grado di organizzare, gestire e comunicare una serie di esercizi a mare secondo l'obiettivo dichiarato a lezione e nei tempi stabiliti"},
        {'peso': 1, 'desc': "E' disponibile a condividere la propria esperienza nautica a disposizione del team"},
    ]},
    {'macro': '5. Consapevolezza del ruolo - Responsabilita, Motivazione, Impegno', 'items': [
        {'peso': 2, 'desc': "Crede in cio che sta facendo e nel ruolo dell'istruttore, come modello di riferimento (atteggiamento e abbigliamento) e non come privilegio. Dimostrando di comprendere le responsabilita annesse al ruolo, condividendo e promuovendo le norme di comportamento in rispetto delle persone (carta dei valori, inclusione, dell'ambiente e della sostenibilita) rispetta ed incorpora la carta dei valori del CVC e il codice Etico"},
        {'peso': 2, 'desc': "E' in grado di mantenere la calma e la lucidita sotto forte stress fisico/emotivo e di infonderla negli altri."},
        {'peso': 2, 'desc': "Gestisce consapevolmente le proprie risorse psicofisiche, e conseguentemente proattivo e disponibile verso istruttori, allievi e staff"},
    ]},
    {'macro': '6. Capacita organizzative e aspetti logistici', 'items': [
        {'peso': 2, 'desc': "E' in grado di gestire e coordinare attivita a mare (comandata mezzi, veleria, scalo e caletta) e a terra (comandata cucina (orari), pulizie (sala pranzo, bagni))"},
        {'peso': 1, 'desc': "E' in grado di gestire e indirizzare le procedure per la manutenzione ordinaria, piccole avarie con i riferimenti Staff"},
        {'peso': 1, 'desc': "Conosce, promuove e segue le procedure di prevenzione (incendi e infortuni) ed emergenza (incendio e infortuni) a terra a mare."},
    ]},
]

SCHEMA_C3 = [
    {'macro': '1. Navigazione a vela', 'items': [
        {'peso': 2, 'desc': "Conduce con buona sicurezza e autonomia un cabinato e il suo equipaggio anche in spazi ristretti"},
        {'peso': 3, 'desc': "Esegue/fa eseguire costantemente tutte le manovre fondamentali del nuovo corso garantendo sicurezza"},
        {'peso': 3, 'desc': "Esegue tutte le manovre con metodo e cognizione di causa, avendo sempre chiara la via di fuga (SN+VI)"},
    ]},
    {'macro': '2. Procedure di sicurezza', 'items': [
        {'peso': 2, 'desc': "Ha consapevolezza della presa in consegna dell'imbarcazione ed esegue verifiche di sicurezza"},
        {'peso': 3, 'desc': "Ha visione di spazio, tempo ed energie dell'equipaggio per rientri e ancoraggi in sicurezza"},
        {'peso': 3, 'desc': "Mantiene il controllo del mezzo ad equipaggio ridotto senza diventare pericoloso"},
    ]},
    {'macro': '3. Didattica alla lavagna e in mare', 'items': [
        {'peso': 3, 'desc': "Organizza i contenuti, esegue una lezione di 25 min, gestisce anche le domande difficili"},
        {'peso': 2, 'desc': "Esegue lezioni a bordo con efficacia, spiega manovre, lascia sbagliare garantendo la sicurezza"},
        {'peso': 2, 'desc': "Valuta il raggiungimento dell'obiettivo didattico, esegue debriefing a bordo con comunicazione positiva"},
    ]},
    {'macro': '4. Capacità gestionale e team – Organizzazione e Comunicazione', 'items': [
        {'peso': 2, 'desc': "Recepisce nuove informazioni, lascia andare vecchie abitudini non in linea con CVC"},
        {'peso': 2, 'desc': "Organizza e comunica il programma della giornata, si coordina con CT via VHF in navigazione di flotta"},
        {'peso': 1, 'desc': "Riesce a lavorare in gruppo evitando assoli"},
    ]},
    {'macro': '5. Consapevolezza del ruolo – Responsabilità, Motivazione, Impegno', 'items': [
        {'peso': 2, 'desc': "È modello di riferimento, prevede le mancanze degli allievi, promuove carta dei valori e inclusione"},
        {'peso': 2, 'desc': "Mantiene calma e lucidità sotto forte stress fisico/emotivo e la infonde negli altri"},
        {'peso': 2, 'desc': "È promotore come leader piuttosto che come persona al comando"},
    ]},
    {'macro': '6. Capacità organizzative e aspetti logistici', 'items': [
        {'peso': 2, 'desc': "Gestisce la comandata a bordo e si coordina con le altre imbarcazioni tenendo conto dell'impatto ambientale"},
        {'peso': 1, 'desc': "Gestisce ed esegue piccole avarie (circuito trinca e 3D) comunicando efficacemente allo staff"},
        {'peso': 1, 'desc': "Conosce, promuove e segue le procedure di presa in carico, monitoraggio e riconsegna barca"},
    ]},
]

SCHEMAS = {'ADV': SCHEMA_ADV, 'Istruttori1': SCHEMA_IS1, 'IstruttoriC3': SCHEMA_C3}
SOGLIE  = {'ADV': None, 'Istruttori1': 66, 'IstruttoriC3': 66}
PESI_VOTI = {'': 0, 'Non svolto': 2, 'Non Raggiunto': 0, 'Da Affinare': 1, 'Sufficiente': 2, 'Buono': 3, 'Ottimo': 4}
VOTI_VALIDI = ['Non svolto', 'Non Raggiunto', 'Da Affinare', 'Sufficiente', 'Buono', 'Ottimo']

def get_grade_cols(corso):
    """Genera le colonne voto per un corso: voto_s{i}_c{j} per ogni sezione/item"""
    schema = SCHEMAS.get(corso, [])
    cols = []
    for si, sec in enumerate(schema):
        for ci, item in enumerate(sec['items']):
            cols.append(f'v_{si}_{ci}')
    return cols

def calcola_totale(corso, grades):
    schema = SCHEMAS.get(corso, [])
    total = 0
    for si, sec in enumerate(schema):
        for ci, item in enumerate(sec['items']):
            key = f'v_{si}_{ci}'
            voto = grades.get(key, '') or ''
            peso = item['peso']
            total += PESI_VOTI.get(voto.strip(), 0) * peso
    return total

def init_db():
    AI  = "SERIAL" if USE_PG else "INTEGER"
    AIP = "" if USE_PG else "AUTOINCREMENT"
    TS  = "TIMESTAMP DEFAULT NOW()" if USE_PG else "TEXT DEFAULT (datetime('now'))"

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'''CREATE TABLE IF NOT EXISTS turni (
            id         {AI} PRIMARY KEY {AIP},
            numero     INTEGER NOT NULL,
            corso      TEXT NOT NULL,
            pwd_hash   TEXT NOT NULL,
            pwd_plain  TEXT NOT NULL,
            capoturno  TEXT NOT NULL,
            email      TEXT,
            soglia     INTEGER DEFAULT 66,
            foto_abilitata INTEGER DEFAULT 0,
            created_at {TS},
            UNIQUE(numero, corso)
        )''')
        cur.execute(f'''CREATE TABLE IF NOT EXISTS allievi (
            id         {AI} PRIMARY KEY {AIP},
            turno      INTEGER NOT NULL,
            corso      TEXT NOT NULL,
            nome       TEXT NOT NULL,
            foto_url   TEXT,
            note       TEXT,
            created_at {TS},
            UNIQUE(turno, corso, nome)
        )''')
        cur.execute(f'''CREATE TABLE IF NOT EXISTS valutazioni (
            id         {AI} PRIMARY KEY {AIP},
            allievo_id INTEGER NOT NULL,
            vkey       TEXT NOT NULL,
            valore     TEXT,
            updated_at {TS},
            UNIQUE(allievo_id, vkey)
        )''')
        cur.execute(f'''CREATE TABLE IF NOT EXISTS valutazioni_op (
            id         {AI} PRIMARY KEY {AIP},
            allievo_id INTEGER NOT NULL,
            vkey       TEXT NOT NULL,
            valore     TEXT,
            updated_at {TS},
            UNIQUE(allievo_id, vkey)
        )''')
        cur.execute(f'''CREATE TABLE IF NOT EXISTS giornaliero (
            id         {AI} PRIMARY KEY {AIP},
            allievo_id INTEGER NOT NULL,
            giorno     INTEGER NOT NULL,
            sezione    INTEGER NOT NULL,
            valore     TEXT,
            nota       TEXT,
            updated_at {TS},
            UNIQUE(allievo_id, giorno, sezione)
        )''')
        cur.execute(f'''CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            tipo       TEXT DEFAULT 'admin',
            turno      INTEGER,
            corso      TEXT,
            foto_ok    INTEGER DEFAULT 0,
            created_at {TS}
        )''')
        conn.commit()

init_db()

def migrate_db():
    try:
        with get_db() as conn:
            cur = conn.cursor()
            if USE_PG:
                # sessions.corso
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='sessions' AND column_name='corso'")
                if not cur.fetchone():
                    cur.execute('ALTER TABLE sessions ADD COLUMN corso TEXT'); conn.commit()
                # sessions.foto_ok
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='sessions' AND column_name='foto_ok'")
                if not cur.fetchone():
                    cur.execute('ALTER TABLE sessions ADD COLUMN foto_ok INTEGER DEFAULT 0'); conn.commit()
                # turni.soglia
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='turni' AND column_name='soglia'")
                if not cur.fetchone():
                    cur.execute('ALTER TABLE turni ADD COLUMN soglia INTEGER DEFAULT 66'); conn.commit()
                # turni.foto_abilitata
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='turni' AND column_name='foto_abilitata'")
                if not cur.fetchone():
                    cur.execute('ALTER TABLE turni ADD COLUMN foto_abilitata INTEGER DEFAULT 0'); conn.commit()
                # giornaliero table (PG)
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name='giornaliero'")
                if not cur.fetchone():
                    cur.execute('''CREATE TABLE IF NOT EXISTS giornaliero (
                        id         SERIAL PRIMARY KEY,
                        allievo_id INTEGER NOT NULL,
                        giorno     INTEGER NOT NULL,
                        sezione    INTEGER NOT NULL,
                        valore     TEXT,
                        nota       TEXT,
                        updated_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(allievo_id, giorno, sezione)
                    )''')
                    conn.commit()
            else:
                cur.execute("PRAGMA table_info(sessions)")
                cols = [r[1] for r in cur.fetchall()]
                if 'corso' not in cols:
                    cur.execute('ALTER TABLE sessions ADD COLUMN corso TEXT'); conn.commit()
                if 'foto_ok' not in cols:
                    cur.execute('ALTER TABLE sessions ADD COLUMN foto_ok INTEGER DEFAULT 0'); conn.commit()
                cur.execute("PRAGMA table_info(turni)")
                cols2 = [r[1] for r in cur.fetchall()]
                if 'soglia' not in cols2:
                    cur.execute('ALTER TABLE turni ADD COLUMN soglia INTEGER DEFAULT 66'); conn.commit()
                if 'foto_abilitata' not in cols2:
                    cur.execute('ALTER TABLE turni ADD COLUMN foto_abilitata INTEGER DEFAULT 0'); conn.commit()
                # giornaliero table (SQLite)
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='giornaliero'")
                if not cur.fetchone():
                    cur.execute('''CREATE TABLE IF NOT EXISTS giornaliero (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        allievo_id INTEGER NOT NULL,
                        giorno     INTEGER NOT NULL,
                        sezione    INTEGER NOT NULL,
                        valore     TEXT,
                        nota       TEXT,
                        updated_at TEXT DEFAULT (datetime('now')),
                        UNIQUE(allievo_id, giorno, sezione)
                    )''')
                    conn.commit()
    except Exception as e:
        print(f"Migration: {e}")

migrate_db()

# ── Auth helpers ──────────────────────────────────────────────────────────────
def check_admin(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('X-Admin-Token', '')
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT token FROM sessions WHERE token={PH} AND tipo='admin'", (token,))
            if not cur.fetchone(): return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return wrapper

def check_turno_auth(turno_num, corso, token):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT token FROM sessions WHERE token={PH} AND (tipo='admin' OR (tipo='turno' AND turno={PH} AND corso={PH}))",
                    (token, turno_num, corso))
        return cur.fetchone() is not None

# ── Static ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# ── Auth endpoints ─────────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    d = request.json or {}
    if d.get('password') != ADMIN_PWD:
        return jsonify({'error': 'Password errata'}), 401
    token = secrets.token_hex(32)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"INSERT INTO sessions(token,tipo) VALUES({PH},{PH})", (token, 'admin'))
        conn.commit()
    return jsonify({'token': token, 'tipo': 'admin'})

@app.route('/api/verify', methods=['GET'])
def verify():
    token = request.headers.get('X-Auth-Token', '')
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT tipo,turno,corso FROM sessions WHERE token={PH}', (token,))
        row = cur.fetchone()
    if not row: return jsonify({'valid': False}), 401
    if USE_PG:
        tipo, turno, corso = row[0], row[1], row[2]
    else:
        tipo, turno, corso = row['tipo'], row['turno'], row['corso']
    return jsonify({'valid': True, 'tipo': tipo, 'turno': turno, 'corso': corso})

@app.route('/api/turno/<int:numero>/exists', methods=['GET'])
def turno_exists(numero):
    corso = request.args.get('corso', '')
    with get_db() as conn:
        cur = conn.cursor()
        if corso:
            cur.execute(f'SELECT id FROM turni WHERE numero={PH} AND corso={PH}', (numero, corso))
            row = cur.fetchone()
            return jsonify({'exists': row is not None})
        return jsonify({'exists': False})

@app.route('/api/turno/login', methods=['POST'])
def turno_login():
    d = request.json or {}
    numero = d.get('numero')
    pwd = d.get('password', '').strip()
    corso = d.get('corso', '').strip()
    capoturno = d.get('capoturno', '').strip()
    email = d.get('email', '').strip()

    if not numero or not pwd or not corso:
        return jsonify({'error': 'Turno, corso e password obbligatori'}), 400
    if corso not in CORSI_VALIDI:
        return jsonify({'error': f'Corso non valido. Scegli tra: {", ".join(CORSI_VALIDI)}'}), 400
    try:
        numero = int(numero)
    except:
        return jsonify({'error': 'Numero turno non valido'}), 400
    if not (1 <= numero <= 60):
        return jsonify({'error': 'Il turno deve essere tra 1 e 60'}), 400

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM turni WHERE numero={PH} AND corso={PH}', (numero, corso))
        turno_dict = row_to_dict(cur.fetchone(), cur)

        if turno_dict is None:
            # Primo accesso: serve capoturno
            if not capoturno:
                return jsonify({'error': 'Prima apertura: inserisci anche il Capo Turno', 'primo_accesso': True}), 400
            try:
                cur.execute(
                    f'INSERT INTO turni(numero,corso,pwd_hash,pwd_plain,capoturno,email) VALUES({PH},{PH},{PH},{PH},{PH},{PH})',
                    (numero, corso, hash_pwd(pwd), pwd, capoturno, email or None)
                )
                conn.commit()
            except Exception as ex:
                conn.rollback()
                return jsonify({'error': 'Errore: ' + str(ex)}), 500
            cur.execute(f'SELECT * FROM turni WHERE numero={PH} AND corso={PH}', (numero, corso))
            turno_dict = row_to_dict(cur.fetchone(), cur)
        else:
            if hash_pwd(pwd) != turno_dict['pwd_hash']:
                return jsonify({'error': 'Password errata per questo turno'}), 401

        token = secrets.token_hex(32)
        # foto abilitata se: password foto speciale OPPURE admin ha abilitato per questo turno
        foto_ok_pwd = 1 if pwd == FOTO_PWD else 0
        foto_ok_turno = 1 if turno_dict.get('foto_abilitata') else 0
        foto_ok = 1 if (foto_ok_pwd or foto_ok_turno) else 0
        cur.execute(
            f"INSERT INTO sessions(token,tipo,turno,corso,foto_ok) VALUES({PH},{PH},{PH},{PH},{PH})",
            (token, 'turno', numero, corso, foto_ok)
        )
        conn.commit()

    return jsonify({
        'token': token, 'tipo': 'turno', 'turno': numero,
        'corso': turno_dict['corso'], 'capoturno': turno_dict['capoturno'],
        'soglia': turno_dict.get('soglia') if turno_dict.get('soglia') is not None else 66,
        'fotoAbilitata': bool(foto_ok)
    })

# ── Allievi ────────────────────────────────────────────────────────────────────
@app.route('/api/allievi/<int:turno>', methods=['GET'])
def get_allievi(turno):
    token = request.headers.get('X-Auth-Token', '')
    corso = request.args.get('corso', '')
    if not check_turno_auth(turno, corso, token):
        return jsonify({'error': 'Non autorizzato'}), 401

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM allievi WHERE turno={PH} AND corso={PH} ORDER BY nome', (turno, corso))
        allievi = rows_to_dicts(cur.fetchall(), cur)

        result = []
        for a in allievi:
            aid = a['id']
            cur.execute(f'SELECT vkey, valore FROM valutazioni WHERE allievo_id={PH}', (aid,))
            grades = {r[0] if USE_PG else r['vkey']: r[1] if USE_PG else r['valore']
                      for r in cur.fetchall()}
            cur.execute(f'SELECT vkey, valore FROM valutazioni_op WHERE allievo_id={PH}', (aid,))
            op_grades = {r[0] if USE_PG else r['vkey']: r[1] if USE_PG else r['valore']
                         for r in cur.fetchall()}
            # Giornaliero: dizionario {giorno_sezione: {valore, nota}}
            cur.execute(f'SELECT giorno, sezione, valore, nota FROM giornaliero WHERE allievo_id={PH}', (aid,))
            giorn = {}
            for r in cur.fetchall():
                g = r[0] if USE_PG else r['giorno']
                s = r[1] if USE_PG else r['sezione']
                v = r[2] if USE_PG else r['valore']
                n = r[3] if USE_PG else r['nota']
                if s == 99:
                    giorn[f'{g}_nota'] = {'nota': n or '', 'valore': ''}
                else:
                    giorn[f'{g}_{s}'] = {'valore': v or '', 'nota': n or ''}
            result.append({**a, 'grades': grades, 'op_grades': op_grades, 'giorn': giorn})

    return jsonify({'allievi': result})

@app.route('/api/allievi/<int:turno>', methods=['POST'])
def add_allievo(turno):
    token = request.headers.get('X-Auth-Token', '')
    d = request.json or {}
    corso = d.get('corso', '')
    nome = d.get('nome', '').strip()
    if not check_turno_auth(turno, corso, token):
        return jsonify({'error': 'Non autorizzato'}), 401
    if not nome:
        return jsonify({'error': 'Nome obbligatorio'}), 400

    with get_db() as conn:
        cur = conn.cursor()
        try:
            if USE_PG:
                cur.execute(
                    f'INSERT INTO allievi(turno,corso,nome) VALUES({PH},{PH},{PH}) RETURNING id',
                    (turno, corso, nome)
                )
                lid = cur.fetchone()[0]
            else:
                cur.execute(
                    f'INSERT INTO allievi(turno,corso,nome) VALUES({PH},{PH},{PH})',
                    (turno, corso, nome)
                )
                lid = cur.lastrowid
            conn.commit()
        except Exception as e:
            conn.rollback()
            return jsonify({'error': 'Allievo già presente o errore: ' + str(e)}), 400

    return jsonify({'ok': True, 'id': lid, 'nome': nome})

@app.route('/api/allievi/<int:allievo_id>', methods=['DELETE'])
def delete_allievo(allievo_id):
    token = request.headers.get('X-Auth-Token', '')
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Non trovato'}), 404
        turno = row[0] if USE_PG else row['turno']
        corso = row[1] if USE_PG else row['corso']
        if not check_turno_auth(turno, corso, token):
            return jsonify({'error': 'Non autorizzato'}), 401
        cur.execute(f'DELETE FROM valutazioni WHERE allievo_id={PH}', (allievo_id,))
        cur.execute(f'DELETE FROM allievi WHERE id={PH}', (allievo_id,))
        conn.commit()
    return jsonify({'ok': True})

@app.route('/api/allievi/<int:allievo_id>/rinomina', methods=['PUT'])
def rinomina_allievo(allievo_id):
    token = request.headers.get('X-Auth-Token', '')
    d = request.json or {}
    nuovo_nome = d.get('nome', '').strip()
    if not nuovo_nome:
        return jsonify({'error': 'Nome obbligatorio'}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Non trovato'}), 404
        turno = row[0] if USE_PG else row['turno']
        corso = row[1] if USE_PG else row['corso']
        if not check_turno_auth(turno, corso, token):
            return jsonify({'error': 'Non autorizzato'}), 401
        # Verifica che il nuovo nome non esista già
        cur.execute(f'SELECT id FROM allievi WHERE turno={PH} AND corso={PH} AND nome={PH} AND id!={PH}',
                    (turno, corso, nuovo_nome, allievo_id))
        if cur.fetchone():
            return jsonify({'error': 'Esiste già un allievo con questo nome'}), 400
        cur.execute(f'UPDATE allievi SET nome={PH} WHERE id={PH}', (nuovo_nome, allievo_id))
        conn.commit()
    return jsonify({'ok': True, 'nome': nuovo_nome})

@app.route('/api/turno/<int:numero>/foto', methods=['PUT'])
@check_admin
def toggle_foto(numero):
    d = request.json or {}
    corso = d.get('corso', '')
    abilitata = 1 if d.get('abilitata') else 0
    if not corso: return jsonify({'error': 'Corso obbligatorio'}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'UPDATE turni SET foto_abilitata={PH} WHERE numero={PH} AND corso={PH}',
                    (abilitata, numero, corso))
        if cur.rowcount == 0:
            return jsonify({'error': 'Turno non trovato'}), 404
        conn.commit()
    return jsonify({'ok': True, 'abilitata': bool(abilitata)})

@app.route('/api/allievi/<int:allievo_id>/note', methods=['PUT'])
def update_note(allievo_id):
    token = request.headers.get('X-Auth-Token', '')
    d = request.json or {}
    note = d.get('note', '')
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Non trovato'}), 404
        turno = row[0] if USE_PG else row['turno']
        corso = row[1] if USE_PG else row['corso']
        if not check_turno_auth(turno, corso, token):
            return jsonify({'error': 'Non autorizzato'}), 401
        cur.execute(f'UPDATE allievi SET note={PH} WHERE id={PH}', (note, allievo_id))
        conn.commit()
    return jsonify({'ok': True})

# ── Valutazioni ────────────────────────────────────────────────────────────────
@app.route('/api/valutazioni/<int:allievo_id>', methods=['PUT'])
def save_valutazione(allievo_id):
    token = request.headers.get('X-Auth-Token', '')
    d = request.json or {}
    grades = d.get('grades', {})

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Allievo non trovato'}), 404
        turno = row[0] if USE_PG else row['turno']
        corso = row[1] if USE_PG else row['corso']
        if not check_turno_auth(turno, corso, token):
            return jsonify({'error': 'Non autorizzato'}), 401

        for vkey, valore in grades.items():
            if valore not in VOTI_VALIDI and valore != '':
                continue
            cur.execute(f'SELECT id FROM valutazioni WHERE allievo_id={PH} AND vkey={PH}', (allievo_id, vkey))
            existing = cur.fetchone()
            if existing:
                cur.execute(f'UPDATE valutazioni SET valore={PH} WHERE allievo_id={PH} AND vkey={PH}',
                            (valore, allievo_id, vkey))
            else:
                cur.execute(f'INSERT INTO valutazioni(allievo_id,vkey,valore) VALUES({PH},{PH},{PH})',
                            (allievo_id, vkey, valore))
        conn.commit()
    return jsonify({'ok': True})

# ── Valutazioni Operative ─────────────────────────────────────────────────────
@app.route('/api/valutazioni-op/<int:allievo_id>', methods=['PUT'])
def save_valutazione_op(allievo_id):
    token = request.headers.get('X-Auth-Token', '')
    d = request.json or {}
    grades = d.get('grades', {})

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Allievo non trovato'}), 404
        turno = row[0] if USE_PG else row['turno']
        corso = row[1] if USE_PG else row['corso']
        if not check_turno_auth(turno, corso, token):
            return jsonify({'error': 'Non autorizzato'}), 401

        for vkey, valore in grades.items():
            if valore not in VOTI_VALIDI and valore != '':
                continue
            cur.execute(f'SELECT id FROM valutazioni_op WHERE allievo_id={PH} AND vkey={PH}', (allievo_id, vkey))
            existing = cur.fetchone()
            if existing:
                cur.execute(f'UPDATE valutazioni_op SET valore={PH} WHERE allievo_id={PH} AND vkey={PH}',
                            (valore, allievo_id, vkey))
            else:
                cur.execute(f'INSERT INTO valutazioni_op(allievo_id,vkey,valore) VALUES({PH},{PH},{PH})',
                            (allievo_id, vkey, valore))
        conn.commit()
    return jsonify({'ok': True})

# ── Valutazioni Giornaliere ───────────────────────────────────────────────────
@app.route('/api/giornaliero/<int:turno>', methods=['GET'])
def get_giornaliero(turno):
    token = request.headers.get('X-Auth-Token', '')
    corso = request.args.get('corso', '')
    if not check_turno_auth(turno, corso, token):
        return jsonify({'error': 'Non autorizzato'}), 401
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'''
            SELECT g.allievo_id, g.giorno, g.sezione, g.valore, g.nota
            FROM giornaliero g
            JOIN allievi a ON g.allievo_id = a.id
            WHERE a.turno={PH} AND a.corso={PH}
            ORDER BY g.allievo_id, g.giorno, g.sezione
        ''', (turno, corso))
        rows = rows_to_dicts(cur.fetchall(), cur)
    return jsonify({'rows': rows})

@app.route('/api/giornaliero/<int:allievo_id>', methods=['PUT'])
def save_giornaliero(allievo_id):
    token = request.headers.get('X-Auth-Token', '')
    d = request.json or {}
    giorno  = d.get('giorno')
    sezione = d.get('sezione')
    valore  = d.get('valore', '')
    nota    = d.get('nota', '')
    try:
        giorno = int(giorno); sezione = int(sezione)
        if not (1 <= giorno <= 7) or not (0 <= sezione <= 5): raise ValueError()
    except:
        return jsonify({'error': 'Parametri non validi'}), 400
    if valore not in VOTI_VALIDI and valore != '':
        return jsonify({'error': 'Valore non valido'}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Allievo non trovato'}), 404
        t = row[0] if USE_PG else row['turno']
        c = row[1] if USE_PG else row['corso']
        if not check_turno_auth(t, c, token):
            return jsonify({'error': 'Non autorizzato'}), 401
        cur.execute(f'SELECT id FROM giornaliero WHERE allievo_id={PH} AND giorno={PH} AND sezione={PH}',
                    (allievo_id, giorno, sezione))
        if cur.fetchone():
            cur.execute(f'UPDATE giornaliero SET valore={PH},nota={PH} WHERE allievo_id={PH} AND giorno={PH} AND sezione={PH}',
                        (valore, nota, allievo_id, giorno, sezione))
        else:
            cur.execute(f'INSERT INTO giornaliero(allievo_id,giorno,sezione,valore,nota) VALUES({PH},{PH},{PH},{PH},{PH})',
                        (allievo_id, giorno, sezione, valore, nota))
        conn.commit()
    return jsonify({'ok': True})

@app.route('/api/giornaliero-nota/<int:allievo_id>', methods=['PUT'])
def save_giornaliero_nota(allievo_id):
    token = request.headers.get('X-Auth-Token', '')
    d = request.json or {}
    giorno = d.get('giorno')
    nota   = d.get('nota', '')
    try:
        giorno = int(giorno)
        if not (1 <= giorno <= 7): raise ValueError()
    except:
        return jsonify({'error': 'Parametri non validi'}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
        row = cur.fetchone()
        if not row: return jsonify({'error': 'Allievo non trovato'}), 404
        t = row[0] if USE_PG else row['turno']
        c = row[1] if USE_PG else row['corso']
        if not check_turno_auth(t, c, token):
            return jsonify({'error': 'Non autorizzato'}), 401
        # sezione=99 per nota
        cur.execute(f'SELECT id FROM giornaliero WHERE allievo_id={PH} AND giorno={PH} AND sezione=99',
                    (allievo_id, giorno))
        if cur.fetchone():
            cur.execute(f'UPDATE giornaliero SET nota={PH} WHERE allievo_id={PH} AND giorno={PH} AND sezione=99',
                        (nota, allievo_id, giorno))
        else:
            cur.execute(f'INSERT INTO giornaliero(allievo_id,giorno,sezione,valore,nota) VALUES({PH},{PH},99,{PH},{PH})',
                        (allievo_id, giorno, '', nota))
        conn.commit()
    return jsonify({'ok': True})

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

@app.route('/api/foto/<int:allievo_id>', methods=['POST'])
def upload_foto(allievo_id):
    import traceback
    try:
        token = request.headers.get('X-Auth-Token', '')
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(f'SELECT turno, corso FROM allievi WHERE id={PH}', (allievo_id,))
            row = cur.fetchone()
            if not row: return jsonify({'error': 'Allievo non trovato'}), 404
            turno = row[0] if USE_PG else row['turno']
            corso = row[1] if USE_PG else row['corso']
            if not check_turno_auth(turno, corso, token):
                return jsonify({'error': 'Non autorizzato'}), 401
            # Verifica permesso foto
            cur.execute(f'SELECT foto_ok FROM sessions WHERE token={PH}', (token,))
            sr = cur.fetchone()
            fok = sr[0] if USE_PG else (sr['foto_ok'] if sr else 0)
            if not fok:
                return jsonify({'error': 'Caricamento foto non abilitato per questo accesso'}), 403

        if 'foto' not in request.files:
            return jsonify({'error': 'Nessun file'}), 400
        file = request.files['foto']
        if not file or not file.filename:
            return jsonify({'error': 'File vuoto'}), 400

        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in ALLOWED_EXT:
            return jsonify({'error': f'Formato .{ext} non supportato'}), 400

        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        nome_file = secure_filename(f"a{allievo_id}.{ext}")
        path = os.path.join(UPLOAD_FOLDER, nome_file)
        file.save(path)

        try:
            from PIL import Image
            img = Image.open(path).convert('RGB')
            w, h = img.size; m = min(w, h)
            img = img.crop(((w-m)//2, (h-m)//2, (w+m)//2, (h+m)//2))
            img = img.resize((100, 100), Image.LANCZOS)
            img.save(path, quality=85)
        except:
            pass

        foto_url = f'/uploads/{nome_file}'
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(f'UPDATE allievi SET foto_url={PH} WHERE id={PH}', (foto_url, allievo_id))
            conn.commit()

        return jsonify({'ok': True, 'foto_url': foto_url})
    except Exception as e:
        return jsonify({'error': str(e), 'trace': traceback.format_exc()[-500:]}), 500

@app.route('/api/foto/all', methods=['DELETE'])
@check_admin
def delete_all_foto():
    cancellate = 0
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute('SELECT id, foto_url FROM allievi WHERE foto_url IS NOT NULL')
            rows = cur.fetchall()
            for row in rows:
                url = row[0 if USE_PG else 'foto_url'] if USE_PG else row['foto_url']
                if USE_PG:
                    url = row[1]
                if url:
                    path = os.path.join(UPLOAD_FOLDER, os.path.basename(url))
                    try:
                        os.remove(path)
                    except:
                        pass
                    cancellate += 1
            cur.execute('UPDATE allievi SET foto_url=NULL')
            conn.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True, 'cancellate': cancellate})

# ── Stats e Admin ──────────────────────────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
@check_admin
def get_stats():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM allievi')
        totale = (cur.fetchone()[0] if USE_PG else cur.fetchone()[0])
        cur.execute('SELECT COUNT(DISTINCT numero) FROM turni')
        n_turni = cur.fetchone()[0]
        cur.execute('SELECT COUNT(DISTINCT capoturno) FROM turni')
        n_istr = cur.fetchone()[0]
        cur.execute('SELECT numero, corso, capoturno, email, pwd_plain, soglia, foto_abilitata FROM turni ORDER BY numero, corso')
        turni = rows_to_dicts(cur.fetchall(), cur)

        # Conteggio allievi per turno/corso
        cur.execute('SELECT turno, corso, COUNT(*) as n FROM allievi GROUP BY turno, corso')
        ac = rows_to_dicts(cur.fetchall(), cur)
        ac_map = {(r['turno'], r['corso']): r['n'] for r in ac}
        for t in turni:
            t['n_allievi'] = ac_map.get((t['numero'], t['corso']), 0)
            if t.get('soglia') is None: t['soglia'] = 66  # default per turni esistenti

    return jsonify({
        'totale_allievi': totale,
        'n_turni': n_turni,
        'n_istruttori': n_istr,
        'turni': turni
    })

@app.route('/api/turno/<int:numero>/soglia', methods=['PUT'])
@check_admin
def update_soglia(numero):
    d = request.json or {}
    corso = d.get('corso', '')
    soglia = d.get('soglia')
    if not corso: return jsonify({'error': 'Corso obbligatorio'}), 400
    try:
        soglia = int(soglia)
        if soglia < 0 or soglia > 999: raise ValueError()
    except:
        return jsonify({'error': 'Soglia non valida (0-999)'}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'UPDATE turni SET soglia={PH} WHERE numero={PH} AND corso={PH}',
                    (soglia, numero, corso))
        if cur.rowcount == 0:
            return jsonify({'error': 'Turno non trovato'}), 404
        conn.commit()
    return jsonify({'ok': True, 'soglia': soglia})

@app.route('/api/valutazioni/all', methods=['GET'])
@check_admin
def get_all_valutazioni():
    q = request.args.get('q', '')
    corso_f = request.args.get('corso', '')
    turno_f = request.args.get('turno', '')
    with get_db() as conn:
        cur = conn.cursor()
        sql = 'SELECT a.*, t.capoturno FROM allievi a JOIN turni t ON a.turno=t.numero AND a.corso=t.corso WHERE 1=1'
        params = []
        if q:
            sql += f' AND a.nome LIKE {PH}'; params.append(f'%{q}%')
        if corso_f:
            sql += f' AND a.corso={PH}'; params.append(corso_f)
        if turno_f:
            try: sql += f' AND a.turno={PH}'; params.append(int(turno_f))
            except: pass
        sql += ' ORDER BY a.turno, a.corso, a.nome'
        cur.execute(sql, params)
        allievi = rows_to_dicts(cur.fetchall(), cur)

        result = []
        for a in allievi:
            aid = a['id']
            cur.execute(f'SELECT vkey, valore FROM valutazioni WHERE allievo_id={PH}', (aid,))
            grades = {r[0] if USE_PG else r['vkey']: r[1] if USE_PG else r['valore']
                      for r in cur.fetchall()}
            totale = calcola_totale(a['corso'], grades)
            result.append({**a, 'grades': grades, 'totale': totale})

    return jsonify({'rows': result, 'total': len(result)})

@app.route('/api/turno/<int:numero>', methods=['DELETE'])
@check_admin
def cancella_turno(numero):
    corso = request.args.get('corso', '')
    if not corso: return jsonify({'error': 'Corso obbligatorio'}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT id FROM allievi WHERE turno={PH} AND corso={PH}', (numero, corso))
        ids = [r[0] if USE_PG else r['id'] for r in cur.fetchall()]
        for aid in ids:
            cur.execute(f'DELETE FROM valutazioni WHERE allievo_id={PH}', (aid,))
        cur.execute(f'DELETE FROM allievi WHERE turno={PH} AND corso={PH}', (numero, corso))
        cur.execute(f'DELETE FROM turni WHERE numero={PH} AND corso={PH}', (numero, corso))
        cur.execute(f'DELETE FROM sessions WHERE tipo={PH} AND turno={PH} AND corso={PH}', ('turno', numero, corso))
        conn.commit()
    return jsonify({'ok': True, 'allievi': len(ids)})

# ── Export CSV ─────────────────────────────────────────────────────────────────
@app.route('/api/export/csv', methods=['GET'])
@check_admin
def export_csv():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT a.*, t.capoturno FROM allievi a JOIN turni t ON a.turno=t.numero AND a.corso=t.corso ORDER BY a.turno, a.corso, a.nome')
        allievi = rows_to_dicts(cur.fetchall(), cur)

    output = io.StringIO()
    output.write('\ufeff')  # BOM per Excel
    writer = csv.writer(output)
    writer.writerow(['Turno', 'Corso', 'Capo Turno', 'Allievo', 'Sezione', 'Criterio', 'Peso', 'Voto', 'Totale'])

    with get_db() as conn:
        cur = conn.cursor()
        for a in allievi:
            aid = a['id']
            cur.execute(f'SELECT vkey, valore FROM valutazioni WHERE allievo_id={PH}', (aid,))
            grades = {r[0] if USE_PG else r['vkey']: r[1] if USE_PG else r['valore']
                      for r in cur.fetchall()}
            totale = calcola_totale(a['corso'], grades)
            schema = SCHEMAS.get(a['corso'], [])
            for si, sec in enumerate(schema):
                for ci, item in enumerate(sec['items']):
                    vkey = f'v_{si}_{ci}'
                    writer.writerow([
                        a['turno'], a['corso'], a['capoturno'], a['nome'],
                        sec['macro'], item['desc'][:80], item['peso'],
                        grades.get(vkey, ''), totale
                    ])

    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv;charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=CVC_Istruttori.csv'})

# ── Backup / Restore ───────────────────────────────────────────────────────────
@app.route('/api/backup', methods=['GET'])
@check_admin
def backup():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('SELECT * FROM turni')
        turni = rows_to_dicts(cur.fetchall(), cur)
        cur.execute('SELECT * FROM allievi')
        allievi = rows_to_dicts(cur.fetchall(), cur)
        cur.execute('SELECT * FROM valutazioni')
        valutazioni = rows_to_dicts(cur.fetchall(), cur)
    data = json.dumps({'turni': turni, 'allievi': allievi, 'valutazioni': valutazioni}, default=str)
    return Response(data, mimetype='application/json',
                    headers={'Content-Disposition': f'attachment; filename=CVC_backup_{date.today()}.json'})

@app.route('/api/restore', methods=['POST'])
@check_admin
def restore():
    file = request.files.get('file')
    if not file: return jsonify({'error': 'Nessun file'}), 400
    try:
        data = json.load(file)
    except:
        return jsonify({'error': 'File JSON non valido'}), 400
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('DELETE FROM valutazioni')
        cur.execute('DELETE FROM allievi')
        cur.execute('DELETE FROM turni')
        cur.execute('DELETE FROM sessions')
        for t in data.get('turni', []):
            cur.execute(f'INSERT INTO turni(numero,corso,pwd_hash,pwd_plain,capoturno,email) VALUES({PH},{PH},{PH},{PH},{PH},{PH})',
                        (t['numero'], t['corso'], t['pwd_hash'], t['pwd_plain'], t['capoturno'], t.get('email')))
        for a in data.get('allievi', []):
            cur.execute(f'INSERT INTO allievi(turno,corso,nome,foto_url,note) VALUES({PH},{PH},{PH},{PH},{PH})',
                        (a['turno'], a['corso'], a['nome'], a.get('foto_url'), a.get('note')))
        for v in data.get('valutazioni', []):
            cur.execute(f'INSERT INTO valutazioni(allievo_id,vkey,valore) VALUES({PH},{PH},{PH})',
                        (v['allievo_id'], v['vkey'], v['valore']))
        conn.commit()
    return jsonify({'ok': True, 'turni': len(data.get('turni', [])), 'allievi': len(data.get('allievi', []))})

@app.route('/api/reset', methods=['POST'])
@check_admin
def reset_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('DELETE FROM valutazioni')
        cur.execute('DELETE FROM allievi')
        cur.execute('DELETE FROM turni')
        cur.execute('DELETE FROM sessions')
        conn.commit()
    return jsonify({'ok': True})

@app.route('/api/check-libs', methods=['GET'])
def check_libs():
    results = {}
    for lib in ['pg8000', 'PIL', 'flask_cors']:
        try:
            __import__(lib)
            results[lib] = 'OK'
        except ImportError as e:
            results[lib] = f'MANCANTE: {e}'
    return jsonify(results)

@app.errorhandler(404)
def not_found(e):
    return send_from_directory('static', 'index.html')

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
