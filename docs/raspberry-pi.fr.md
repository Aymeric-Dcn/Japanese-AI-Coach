# Japanese Coach sur un Raspberry Pi (téléphone + PC, une seule progression)

*English version: [raspberry-pi.md](raspberry-pi.md)*

C'est optionnel : sans ça, l'app sur ton PC (le `.exe` ou `python server.py`) marche exactement comme avant.

L'idée : un petit ordinateur toujours allumé (un Raspberry Pi 2, 3 ou plus récent) fait tourner l'app, et tu
l'ouvres depuis ton téléphone **et** ton PC. Il n'y a qu'une base de données : révisions, série de jours et progrès
sont les mêmes partout. [Tailscale](https://tailscale.com) la rend joignable de partout (en 4G aussi), et
seulement par tes appareils.

```
 téléphone ─┐                                    ┌─ Ollama du PC (optionnel, quand le PC est allumé)
            ├── Tailscale (HTTPS) ── Raspberry Pi ┤
 PC ────────┘      app + progrès (coach.db)       └─ ou un modèle cloud (clé Claude / OpenAI)
```

Qui fait quoi :

| | Sur le Pi | Reste sur le PC |
|---|---|---|
| Exercices, révisions, examens JLPT, progrès | ✓ | |
| Nouveaux exercices de la banque partagée | ✓ (au démarrage, puis chaque jour) | |
| Génération d'exercices depuis ton deck Anki | | ✓ (puis relecture + publication dans la banque : le Pi les récupère) |
| Le prof (chat) | ✓ avec une clé cloud, ou avec l'Ollama du PC quand il est allumé | |

Le Pi n'a besoin que de Python : ni SudachiPy, ni Ollama, ni Anki. Un Pi 2 (1 Go de RAM) suffit.

## 1. Vérifier le Pi

```sh
python3 --version     # 3.8 ou plus (Raspberry Pi OS « Bullseye » = 3.9, « Bookworm » = 3.11)
tailscale status      # le Pi, ton PC et ton téléphone doivent apparaître
```

Avec Python 3.7 ou plus ancien (Raspberry Pi OS « Buster »), installe d'abord un **Raspberry Pi OS Lite** récent
(Raspberry Pi Imager ; la version 32 bits pour un Pi 2).

## 2. Installer l'app

```sh
sudo apt install -y git
git clone https://github.com/Aymeric-Dcn/Japanese-AI-Coach.git
cd Japanese-AI-Coach
```

## 3. Ramener ta progression depuis le PC

Dans PowerShell sur le PC, depuis le dossier de l'app (`C:\Projects\Japanese-AI-Coach` ; pour le `.exe` :
`%LOCALAPPDATA%\JapaneseCoach`). Remplace `pi@raspberrypi` par ton utilisateur et le nom Tailscale du Pi :

```powershell
scp data\coach.db data\settings.json data\known.json data\lexicon.db data\grammar.json data\kanji.json pi@raspberrypi:Japanese-AI-Coach/data/
```

- `coach.db` = exercices et progrès, `known.json` + `lexicon.db` + `grammar.json` + `kanji.json` = ce que ton deck
  Anki dit que tu connais, `settings.json` = les réglages (clé API comprise).
- Ne copie pas `bank.db` (240 Mo, il ne sert qu'à générer).
- Ferme l'app sur le PC avant, pour que `coach.db` soit complet.

À partir de là, **c'est la copie du Pi qui compte** : entraîne-toi sur l'adresse du Pi, pas dans l'app du PC
(sinon les deux progressions partent chacune de leur côté). Après une nouvelle synchro Anki sur le PC, recopie
`known.json`, `lexicon.db`, `grammar.json` et `kanji.json` pour que le Pi connaisse tes nouveaux mots.

## 4. Le lancer comme service

```sh
sh deploy/install-pi.sh
```

L'app démarre maintenant avec le Pi et redémarre toute seule si elle s'arrête. Commandes utiles :

```sh
journalctl -u japanese-coach -f            # le journal
sudo systemctl restart japanese-coach      # après un changement
git pull && sudo systemctl restart japanese-coach   # mettre l'app à jour
```

## 5. L'ouvrir depuis le téléphone et le PC

```sh
sudo tailscale serve --bg 8000
```

Tailscale affiche une adresse du genre `https://raspberrypi.ton-tailnet.ts.net`. Seuls les appareils de ton
tailnet peuvent l'ouvrir (si Tailscale le demande, active les certificats HTTPS dans la console d'admin :
DNS → HTTPS Certificates).

- **Téléphone** : ouvre l'adresse dans Chrome (Android) ou Safari (iPhone), puis *Ajouter à l'écran d'accueil* /
  *Installer l'application*. Elle s'ouvre en plein écran comme une app, avec son icône.
- **PC** : ouvre la même adresse dans Edge ou Chrome, puis ⋯ → *Applications* → *Installer ce site en tant
  qu'application*.

L'app elle-même n'écoute toujours que sur le Pi (127.0.0.1) : Tailscale est la seule porte d'entrée.

## 6. Le prof (chat)

Deux choix, tous les deux dans `data/settings.json` sur le Pi (ou via Progrès → L'application → Relancer
l'assistant) :

- **Une clé cloud** (Claude ou OpenAI) : marche à toute heure, même PC éteint. Le plus simple.
- **L'Ollama du PC**, quand le PC est allumé. Sur le PC, fais écouter Ollama sur le réseau, une fois :
  ```powershell
  setx OLLAMA_HOST 0.0.0.0
  ```
  puis quitte Ollama (icône près de l'horloge) et relance-le. Sur le Pi, ajoute le nom Tailscale du PC dans
  `data/settings.json` :
  ```json
  "ollama_url": "mon-pc"
  ```
  (`mon-pc`, `100.x.y.z` ou `http://mon-pc:11434` marchent tous) puis `sudo systemctl restart japanese-coach`.
  Ollama n'a pas de mot de passe : le pare-feu de Windows et Tailscale le gardent privé, mais n'ouvre pas le
  port 11434 sur ta box.

## Options de `server.py`

| | |
|---|---|
| `--port 8000` | le port |
| `--host 127.0.0.1` | où écouter. Par défaut : cet ordinateur seulement. `--host 0.0.0.0` = tous les réseaux de l'ordinateur : il n'y a pas de mot de passe, donc seulement sur un réseau privé |
| `--ollama mon-pc:11434` | l'Ollama à utiliser (sinon le réglage `ollama_url`, sinon cet ordinateur) |
