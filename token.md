# Configurazione GitHub Token

## Situazione Attuale

Il token GitHub è salvato nel **Windows Credential Manager**.

Quando `gestisci_gare.py` esegue `git push`, le credenziali vengono caricate automaticamente da lì.

---

## Se Cambi il Token

### Opzione 1: Aggiornamento Semplice (Consigliato)

**Nel PowerShell:**

```powershell
$token = "ghp_NUOVO_TOKEN_QUI"
@"
protocol=https
host=github.com
username=il-bonvi
password=$token
"@ | git credential approve

Write-Host "✅ Token aggiornato!"
```

Sostituisci `NUOVO_TOKEN_QUI` con il tuo nuovo token da GitHub.

### Opzione 2: Rimuovere Tutto e Riconfigurare

Se vuoi cancellare le credenziali precedenti e riconfigurare da zero:

#### Passo 1: Rimuovere Credenziali Vecchie

**Nel PowerShell:**

```powershell
@"
protocol=https
host=github.com
username=il-bonvi
"@ | git credential reject

Write-Host "✅ Credenziali rimosse"
```

#### Passo 2: Aggiungere Nuovo Token

```powershell
$token = "ghp_NUOVO_TOKEN_QUI"
@"
protocol=https
host=github.com
username=il-bonvi
password=$token
"@ | git credential approve

Write-Host "✅ Nuovo token salvato!"
```

### Opzione 3: Usare Windows Credential Manager GUI

1. Apri **Credential Manager** (cerca "Credential Manager" in Windows)
2. Vai a **Windows Credentials**
3. Cerca `git:https://github.com`
4. Clicca su di essa e modifica la password (il token)
5. Salva

---

## Se il Token È Scaduto o Non Funziona

Se `git push` da `gestisci_gare.py` non funziona:

1. **Verifica il token** su https://github.com/settings/tokens
2. **Rigenera il token** se scaduto
3. **Aggiorna il Credential Manager** usando uno dei metodi sopra

---

## Dove Sono Salvate le Credenziali?

- **Windows**: Credential Manager locale (`Control Panel > User Accounts > Credential Manager`)
- **Nel registro**: `HKEY_CURRENT_USER\Software\Git Credential Manager`

Non sono salvate come file di testo, sono crittografate da Windows.

---

## Alternativa: Usare SSH (Più Sicuro)

Se preferisci evitare di salvare token come password, puoi usare **SSH keys**:

```powershell
# Configura SSH per il repository
git remote set-url origin git@github.com:il-bonvi/bonvi-race-database.git
```

Questo richiede di avere una SSH key configurata, ma è più sicuro perché non dipende da password/token testuali.

---

## Comandi Utili

**Verifica quali credenziali sono salvate:**
```powershell
git credential fill < $null
```

**Testa la connessione:**
```powershell
git pull --dry-run
```

**Verifica il remote attuale:**
```powershell
git remote -v
```

---

**Domande?** Controlla il file `gestisci_gare.py` linea ~460 dove è implementata la funzione `git_push_changes()`.
