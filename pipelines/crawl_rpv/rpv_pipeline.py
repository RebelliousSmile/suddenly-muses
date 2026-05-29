#!/usr/bin/env python3
"""
Ren'Py Corpus Pipeline — Pipeline complet pour collecter un corpus RP Ren'Py

Combination de :
1. Recherche GitHub pour trouver de vrais VN Ren'Py
2. Scanner de dialogue pour identifier les fichiers pertinents
3. Génération de corpus synthétique comme fallback

Usage :
    python scripts/crawl_rpv/rpv_pipeline.py --output data/renpy-corpus.jsonl
    python scripts/crawl_rpv/rpv_pipeline.py --generate-only --output data/renpy-corpus.jsonl
    python scripts/crawl_rpv/rpv_pipeline.py --scan-only --repos data/renpy-repos.json
    python scripts/crawl_rpv/rpv_pipeline.py --hybrid --output data/renpy-corpus.jsonl
"""

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from generate_corpus import generate_sample

# === Patterns de détection de dialogue Ren'Py ===
RENPY_DIALOGUE_PATTERNS = {
    "character_dialogue": re.compile(r'^[a-zA-Z_]\w*\s+"[^"]{3,}"', re.MULTILINE),
    "define_character": re.compile(r'define\s+\w+\s*=\s*Character\(', re.MULTILINE),
    "say_screen": re.compile(r'screen\s+\w*say\s*\(', re.MULTILINE),
    "choice_screen": re.compile(r'screen\s+\w*choice\s*\(', re.MULTILINE),
    "narration": re.compile(r'^n\s+"[^"]{3,}"', re.MULTILINE),
    "label": re.compile(r'^label\s+\w+\s*:', re.MULTILINE),
}

# Patterns pour identifier les OUTILS (à exclure)
TOOL_PATTERNS = [
    re.compile(r'unrpa|renpy-translator|vnr-server|GalTransl|ai4visualnovel', re.IGNORECASE),
    re.compile(r'Analyzer|analyzer|translation.tool', re.IGNORECASE),
    re.compile(r'Decompiler|decompiler|disassemble|unpack|extract', re.IGNORECASE),
]


class RenPyDialogueScanner:
    """Scanner les fichiers dialogue dans un projet Ren'Py."""
    
    def __init__(self, token=None):
        self.token = token
        
    def is_tool_repo(self, repo_info):
        """Vérifier si un repo est un outil (pas un VN)."""
        name = repo_info.get('name', '')
        description = repo_info.get('description', '')
        full_name = repo_info.get('full_name', '')
        
        combined = f"{name} {description} {full_name}".lower()
        
        for pattern in TOOL_PATTERNS:
            if pattern.search(combined):
                return True
        return False
    
    def scan_github_repo(self, repo_full_name, max_files=50):
        """Scanner un repo GitHub pour les dialogues."""
        branches = ['main', 'master']
        tree = []
        found_branch = None
        
        for branch in branches:
            url = f"https://api.github.com/repos/{repo_full_name}/git/trees/{branch}?recursive=1"
            headers = self._headers()
            response = requests.get(url, headers=headers, timeout=10.0)

            if response.status_code == 200:
                tree = response.json().get('tree', [])
                found_branch = branch
                break
        
        if not tree:
            return {'files': [], 'error': 'Impossible de récupérer le tree'}
        
        # Filtrer les fichiers .rpy et .py
        relevant_files = [
            item for item in tree
            if item['type'] == 'blob' and item['path'].endswith(('.rpy', '.py'))
        ]
        
        # Analyser chaque fichier
        analyzed = 0
        results = []
        max_size = 30000
        
        for item in relevant_files:
            path = item['path']
            
            # Skip les dépendances
            if any(skip in path for skip in ['python-packages', 'node_modules', '.git', '__pycache__', 'vendor']):
                continue
            
            # Skip les gros fichiers
            if item.get('size', 0) > max_size:
                continue
            
            # Récupérer le contenu
            raw_url = f"https://raw.githubusercontent.com/{repo_full_name}/{found_branch}/{path}"
            headers = self._headers()
            response = requests.get(raw_url, headers=headers, timeout=10.0)
            
            if response.status_code == 200:
                content = response.text
                score = self._score_content(content, path)
                
                if score > 0:
                    results.append({
                        'path': path,
                        'score': score,
                        'size': item.get('size', 0),
                        'github_url': f"https://github.com/{repo_full_name}/blob/{found_branch}/{path}",
                        'content_preview': content[:500]
                    })
                    analyzed += 1
            
            # Rate limiting
            if analyzed % 5 == 0:
                time.sleep(0.5)
        
        # Trier par score
        results.sort(key=lambda x: x['score'], reverse=True)
        
        return {
            'files': results,
            'analyzed': analyzed,
            'total_files': len(relevant_files),
            'branch': found_branch
        }
    
    def _score_content(self, content, filepath):
        """Score un fichier par son contenu dialogue."""
        score = 0
        filename = os.path.basename(filepath).lower()
        
        # Score par nom
        dialogue_names = ['script', 'main', 'story', 'dialogue', 'screens', 'character']
        if any(name in filename for name in dialogue_names):
            score += 20
        
        # Score par patterns
        for pattern_name, pattern in RENPY_DIALOGUE_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                lines = content.split('\n')
                dialogue_lines = sum(1 for line in lines if pattern.search(line))
                
                if pattern_name == "character_dialogue":
                    score += min(dialogue_lines * 3, 50)
                elif pattern_name == "define_character":
                    score += 15
                elif pattern_name == "say_screen":
                    score += 25
                elif pattern_name == "choice_screen":
                    score += 20
                elif pattern_name == "narration":
                    score += min(dialogue_lines * 2, 30)
                elif pattern_name == "label":
                    score += 5
        
        return min(score, 100)
    
    def _headers(self):
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Suddenly-RP-Model-Builder/1.0"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers


def discover_repos(max_results=50, min_stars=5):
    """Découvrir les projets Ren'Py sur GitHub."""
    print("🔍 Recherche de projets Ren'Py sur GitHub...")
    
    # Multiple queries to maximize results
    queries = [
        "renpy stars:>5",
        "renpy stars:>10",
    ]
    
    repos = {}
    for query in queries:
        result = search_repositories(query, per_page=100)
        if result and "items" in result:
            for item in result["items"]:
                repos[item.get("full_name")] = item
    
    if not repos:
        print("⚠️  Aucune recherche n'a donné de résultats")
        return []
    
    result_list = list(repos.values())
    print(f"   → {len(result_list)} repos trouvés")
    
    # Filtrer
    filtered = filter_repos(result_list, min_stars=min_stars)
    print(f"   → {len(filtered)} repos après filtrage")
    
    return filtered


def search_repositories(query, page=1, per_page=100):
    """Rechercher des repositories GitHub."""
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "page": page, "per_page": per_page, "sort": "stars", "order": "desc"}
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Suddenly-RP-Builder/1.0"}
    
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 403:
            print("⚠️  Rate limit GitHub")
            return []
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return {}


def filter_repos(repos, min_stars=5):
    """Filtrer les repos."""
    filtered = []
    for repo in repos:
        if repo.get("stargazers_count", 0) < min_stars:
            continue
        filtered.append(repo)
    return filtered


def run_scan_mode(repos, token=None):
    """Mode scan : scanner les repos pour trouver les dialogues."""
    print("\n🔍 Scan des fichiers dialogue...")
    
    scanner = RenPyDialogueScanner(token=token)
    results = []
    
    for i, repo in enumerate(repos[:20]):  # Limiter à 20 pour ne pas rate-limit
        name = repo.get("full_name", "")
        stars = repo.get("stargazers_count", 0)
        
        # Skip les outils
        if scanner.is_tool_repo(repo):
            print(f"   [{i+1}/20] {name} ({stars}⭐) ⚠️ Outil, exclu")
            continue
        
        print(f"   [{i+1}/20] {name} ({stars}⭐) — scan dialogue...", end=" ")
        
        scan_result = scanner.scan_github_repo(name)
        
        if scan_result and scan_result['files']:
            relevant = [f for f in scan_result['files'] if f['score'] >= 20]
            if relevant:
                print(f"✅ {len(relevant)} fichiers")
                results.append({
                    'repo': name,
                    'stars': stars,
                    'files': relevant[:10]
                })
                
                for f in relevant[:3]:
                    print(f"      {f['score']:3d}/100  {f['path']}")
            else:
                print("❌ Pas de dialogue")
        else:
            print("❌ Pas de dialogue")
        
        time.sleep(1)

    return results


def run_generate_mode(output_file, count=200):
    """Mode génération : créer un corpus synthétique."""
    print(f"\n📝 Génération de {count} exemples Ren'Py...")
    
    entries = []
    for i in range(count):
        try:
            sample = generate_sample()
            entries.append(sample)
        except Exception as e:
            print(f"   ⚠️  Échec exemple {i+1}: {e}")
            continue
    
    if entries:
        with open(output_file, 'w', encoding='utf-8') as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        
        print(f"   ✅ {len(entries)} exemples générés → {output_file}")
    
    return entries


def run_hybrid_mode(output_file, max_repos=10, generate_count=50):
    """Mode hybride : scan + génération."""
    print("🔄 Mode hybride : scan GitHub + génération fallback")
    
    repos = discover_repos(max_results=max_repos, min_stars=5)
    scanned_results = run_scan_mode(repos)
    
    # Compter les fichiers trouvés
    total_files = sum(len(r['files']) for r in scanned_results)
    print(f"\n📊 {total_files} fichiers dialogue trouvés sur GitHub")
    
    if total_files == 0:
        print("⚠️  Aucun dialogue trouvé, fallback vers génération...")
        return run_generate_mode(output_file, generate_count)
    
    # Exporter les résultats du scan
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(scanned_results, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Résultats sauvegardés dans {output_file}")
    print(f"📊 {len(scanned_results)} repos avec dialogue")
    
    return scanned_results


def main():
    parser = argparse.ArgumentParser(description="Ren'Py Corpus Pipeline")
    
    # Mode
    parser.add_argument("--generate", action="store_true", help="Mode génération seulement")
    parser.add_argument("--scan", action="store_true", help="Mode scan seulement")
    parser.add_argument("--hybrid", action="store_true", help="Mode hybride (scan + fallback)")
    parser.add_argument("--output", default="data/renpy-corpus.jsonl", help="Fichier sortie")
    parser.add_argument("--count", type=int, default=200, help="Nombre d'exemples (génération)")
    parser.add_argument("--max-repos", type=int, default=10, help="Max repos à scanner")
    parser.add_argument("--min-stars", type=int, default=5, help="Min étoiles")
    parser.add_argument("--token", help="Token GitHub (optionnel)")
    parser.add_argument("--repos-json", help="Fichier JSON de repos (scan mode)")
    
    args = parser.parse_args()
    
    # Mode génération
    if args.generate:
        entries = run_generate_mode(args.output, args.count)
        return entries
    
    # Mode scan
    if args.scan:
        if args.repos_json:
            with open(args.repos_json, 'r') as f:
                repos = json.load(f)
            results = run_scan_mode(repos, token=args.token)
        else:
            repos = discover_repos(max_results=args.max_repos, min_stars=args.min_stars)
            results = run_scan_mode(repos, token=args.token)
        return results
    
    # Mode hybride (default)
    if args.hybrid:
        results = run_hybrid_mode(args.output, args.max_repos, args.count)
        return results
    
    # Par défaut : mode hybride
    print("=== Ren'Py Corpus Pipeline ===")
    print("Usage:")
    print("  python rpv_pipeline.py --generate --output data/renpy-corpus.jsonl")
    print("  python rpv_pipeline.py --scan --repos data/renpy-repos.json")
    print("  python rpv_pipeline.py --hybrid --output data/renpy-corpus.jsonl")


if __name__ == "__main__":
    main()
