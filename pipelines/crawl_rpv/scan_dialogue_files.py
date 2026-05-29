#!/usr/bin/env python3
"""
Ren'Py Dialogue Scanner — Scanne les fichiers .rpy ET .py pour détecter les dialogues

Un vrai VN Ren'Py contient :
  - Des dialogues character "texte" dans .rpy
  - Des screens de dialogue (say, choice) dans screens.rpy ou screens.py
  - Des personnages définis (define e = Character('Eileen'))

Usage :
    python scripts/crawl_rpv/scan_dialogue_files.py --local-path /path/to/repo
    python scripts/crawl_rpv/scan_dialogue_files.py --github user/repo
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests

# Patterns de détection de dialogue Ren'Py
RENPY_DIALOGUE_PATTERNS = {
    "character_dialogue": re.compile(r'^[a-zA-Z_]\w*\s+"[^"]{3,}"', re.MULTILINE),
    "narration": re.compile(r'^n\s+"[^"]{3,}"', re.MULTILINE),
    "define_character": re.compile(r'define\s+\w+\s*=\s*Character\(', re.MULTILINE),
    "say_screen": re.compile(r'screen\s+\w*say\s*\(', re.MULTILINE),
    "choice_screen": re.compile(r'screen\s+\w*choice\s*\(', re.MULTILINE),
    "label": re.compile(r'^label\s+\w+\s*:', re.MULTILINE),
}

# Patterns pour identifier les outils Ren'Py (à exclure)
TOOL_PATTERNS = [
    re.compile(r'unrpa|renpy-translator|vnr-server|GalTransl|ai4visualnovel', re.IGNORECASE),
    re.compile(r'Analyzer|analyzer|translation.tool', re.IGNORECASE),
    re.compile(r'Decompiler|decompiler|disassemble|unpack|extract', re.IGNORECASE),
]

# Noms de fichiers typiques de dialogue
DIALOGUE_FILE_NAMES = [
    'script.rpy', 'main.rpy', 'story.rpy', 'dialogue.rpy',
    'screens.rpy', 'screens.py', 'options.rpy',
    'character.rpy', 'choices.rpy', 'narrative.rpy',
]


class RenPyDialogueScanner:
    """Scanner les fichiers dialogue dans un projet Ren'Py."""
    
    def __init__(self, local_path=None, github_repo=None, token=None):
        self.local_path = local_path
        self.github_repo = github_repo
        self.token = token
        self.files = {}  # path -> {score, content, type}
        
    def scan(self):
        """Scan local ou GitHub et retourne les fichiers avec dialogue."""
        if self.local_path:
            self._scan_local()
        elif self.github_repo:
            self._scan_github()
        
        # Trier par score décroissant
        return sorted(
            self.files.items(),
            key=lambda x: x[1]['score'],
            reverse=True
        )
    
    def _scan_local(self):
        """Scanner un projet local."""
        path = Path(self.local_path)
        
        for root, _, filenames in os.walk(path):
            for filename in filenames:
                if filename.endswith(('.rpy', '.py')):
                    filepath = os.path.join(root, filename)
                    result = self._analyze_file(str(filepath))
                    if result and result['score'] > 0:
                        self.files[filepath] = result
    
    def _scan_github(self):
        """Scanner un repo GitHub."""
        # Récupérer le tree du repo
        branches = ['main', 'master']
        tree = []
        
        for branch in branches:
            url = f"https://api.github.com/repos/{self.github_repo}/git/trees/{branch}?recursive=1"
            headers = self._headers()
            response = requests.get(url, headers=headers, timeout=10.0)

            if response.status_code == 200:
                tree = response.json().get('tree', [])
                break
        
        if not tree:
            print(f"   ⚠️  Impossible de récupérer le tree de {self.github_repo}")
            return
        
        # Filtrer les fichiers .rpy et .py
        relevant_files = [
            item for item in tree
            if item['type'] == 'blob' and item['path'].endswith(('.rpy', '.py'))
        ]
        
        print(f"   📄 {len(relevant_files)} fichiers .rpy/.py trouvés")
        
        # Analyser chaque fichier (limiter pour ne pas surcharger l'API)
        max_size = 50000  # Max 50Ko par fichier
        analyzed = 0
        
        for item in relevant_files:
            path = item['path']
            
            # Skip les dépendances
            if any(skip in path for skip in ['python-packages', 'node_modules', '.git', '__pycache__']):
                continue
            
            # Récupérer le contenu
            raw_url = f"https://raw.githubusercontent.com/{self.github_repo}/{branch}/{path}"
            headers = self._headers()
            response = requests.get(raw_url, headers=headers, timeout=10.0)
            
            if response.status_code == 200:
                content = response.text[:max_size]
                result = self._analyze_file(path, content=content)
                if result and result['score'] > 0:
                    result['github_url'] = f"https://github.com/{self.github_repo}/blob/{branch}/{path}"
                    self.files[path] = result
                    analyzed += 1
            
            # Rate limiting
            if analyzed % 10 == 0:
                time.sleep(0.5)
        
        print(f"   ✅ {analyzed} fichiers avec dialogue trouvés")
    
    def _analyze_file(self, filepath, content=None):
        """Analyser un fichier et retourner son score de dialogue."""
        try:
            if content is None:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
        except Exception:
            return None
        
        if len(content) > 500000:
            return None  # Fichier trop gros
        
        score = 0
        details = []
        
        # Score par nom de fichier
        filename = os.path.basename(filepath).lower()
        if filename in DIALOGUE_FILE_NAMES:
            score += 30
            details.append(f"nom ({filename})")
        elif '.rpy' in filepath:
            score += 10
            details.append("extension .rpy")
        elif '.py' in filepath and any(x in filepath for x in ['screen', 'script', 'dialogue', 'character']):
            score += 20
            details.append("nom .py pertinent")
        
        # Score par patterns de contenu
        for pattern_name, pattern in RENPY_DIALOGUE_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                # Compter les lignes de dialogue
                lines = content.split('\n')
                dialogue_lines = sum(1 for line in lines if pattern.search(line))
                
                if pattern_name == "character_dialogue":
                    score += min(dialogue_lines * 2, 40)
                    details.append(f"{dialogue_lines} dialogues")
                elif pattern_name == "define_character":
                    score += 15
                    details.append(f"{len(matches)} personnages")
                elif pattern_name == "say_screen":
                    score += 25
                    details.append("screen say")
                elif pattern_name == "choice_screen":
                    score += 20
                    details.append("screen choice")
                elif pattern_name == "narration":
                    score += min(dialogue_lines, 20)
                    details.append(f"{dialogue_lines} narrations")
                elif pattern_name == "label":
                    score += 5
                    details.append(f"{len(matches)} labels")
        
        return {
            'score': min(score, 100),
            'details': details,
            'content': content[:10000]  # Limiter le contenu retourné
        }
    
    def _headers(self):
        """Headers pour les requêtes GitHub."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Suddenly-RP-Model-Builder/1.0"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers


def is_tool_repo(repo_info):
    """Vérifier si un repo est un outil (pas un VN)."""
    name = repo_info.get('name', '')
    description = repo_info.get('description', '')
    full_name = repo_info.get('full_name', '')
    
    combined = f"{name} {description} {full_name}".lower()
    
    for pattern in TOOL_PATTERNS:
        if pattern.search(combined):
            return True
    
    return False


def scan_github_repos(repo_list, token=None):
    """Scanner plusieurs repos GitHub et retourner les résultats."""
    results = []
    
    for i, repo_info in enumerate(repo_list):
        name = repo_info.get('full_name', '')
        stars = repo_info.get('stargazers_count', 0)
        
        # Vérifier si c'est un outil
        if is_tool_repo(repo_info):
            print(f"   [{i+1}/{len(repo_list)}] {name} ({stars}⭐) ⚠️ Outil, exclu")
            continue
        
        print(f"   [{i+1}/{len(repo_list)}] {name} ({stars}⭐) — scan dialogue...", end=" ")
        
        scanner = RenPyDialogueScanner(
            github_repo=name,
            token=token
        )
        
        scored_files = scanner.scan()
        
        if scored_files:
            relevant = [(path, info) for path, info in scored_files if info['score'] >= 20]
            print(f"✅ {len(relevant)} fichiers")
            
            for path, info in relevant[:5]:
                print(f"      {info['score']:3d}/100  {path}")
                if info.get('details'):
                    print(f"         → {', '.join(info['details'][:3])}")
            
            results.append({
                'repo': name,
                'stars': stars,
                'files': [
                    {
                        'path': path,
                        'score': info['score'],
                        'details': info['details'],
                        'github_url': info.get('github_url', '')
                    }
                    for path, info in relevant
                ]
            })
        else:
            print("❌ Aucun dialogue")
        
        # Rate limiting
        time.sleep(1)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scanner les fichiers dialogue Ren'Py (.rpy + .py)"
    )
    parser.add_argument("--local-path", help="Chemin local du projet")
    parser.add_argument("--github", help="Nom du repo GitHub (user/repo)")
    parser.add_argument("--repos-json", help="Fichier JSON de repos à scanner")
    parser.add_argument("--token", help="Token GitHub (optionnel)")
    parser.add_argument("--output", help="Fichier JSON de sortie")
    parser.add_argument("--min-score", type=int, default=20, help="Score minimum")
    
    args = parser.parse_args()
    
    if args.local_path:
        scanner = RenPyDialogueScanner(local_path=args.local_path)
        scored = scanner.scan()
        
        print(f"\n✅ {len(scored)} fichiers trouvés (score ≥ {args.min_score})")
        for path, info in scored:
            if info['score'] >= args.min_score:
                print(f"  {info['score']:3d}/100  {path}")
                print(f"         → {', '.join(info['details'][:3])}")
        
    elif args.github:
        scanner = RenPyDialogueScanner(github_repo=args.github)
        scored = scanner.scan()
        
        print(f"\n✅ {len(scored)} fichiers trouvés dans {args.github}")
        for path, info in scored:
            if info['score'] >= args.min_score:
                print(f"  {info['score']:3d}/100  {path}")
                print(f"         → {', '.join(info['details'][:3])}")
                
    elif args.repos_json:
        with open(args.repos_json, 'r', encoding='utf-8') as f:
            repo_list = json.load(f)
        
        results = scan_github_repos(repo_list, token=args.token)
        
        if results:
            print(f"\n📊 {len(results)} repos avec dialogue trouvé(s)")
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                print(f"💾 Sauvegardé dans {args.output}")
    
    else:
        print("⚠️  Spécifiez --local-path, --github ou --repos-json")


if __name__ == "__main__":
    main()
