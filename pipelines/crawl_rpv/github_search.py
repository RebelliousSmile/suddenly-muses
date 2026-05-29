#!/usr/bin/env python3
"""
Ren'Py Corpus Discovery — GitHub Search
Recherche et télécharge les projets Ren'Py publics sur GitHub.

Usage:
    python scripts/crawl_rpv/github_search.py --limit 50 --lang fr --output data/renpy-repos.json
    python scripts/crawl_rpv/github_search.py --since 2020 --stars 10
"""

import requests
import json
import argparse
import time
import os
import subprocess
from datetime import datetime


def get_gh_token():
    """Détecter automatiquement le token GitHub depuis 'gh auth' ou GITHUB_TOKEN env var."""
    # 1. Vérifier GITHUB_TOKEN env var
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    
    # 2. Détecter le token gh automatiquement
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    return None


def search_github(query, page=1, per_page=100):
    """Rechercher dans le code GitHub."""
    url = "https://api.github.com/search/code"
    params = {
        "q": query,
        "page": page,
        "per_page": per_page,
    }
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Suddenly-RP-Model-Builder/1.0"
    }
    
    # Token GitHub auto-detecté (gh auth token ou GITHUB_TOKEN)
    token = get_gh_token()
    if token:
        headers["Authorization"] = f"token {token}"
        params["per_page"] = 100  # 100 req/min sans token
    
    response = requests.get(url, params=params, headers=headers, timeout=10.0)

    if response.status_code == 403:
        print(f"⚠️  Rate limit GitHub. Utiliser GITHUB_TOKEN environ var.")
        return []

    response.raise_for_status()
    return response.json()


def search_repositories(query, page=1, per_page=100):
    """Rechercher des repositories GitHub."""
    url = "https://api.github.com/search/repositories"
    params = {
        "q": query,
        "page": page,
        "per_page": per_page,
        "sort": "stars",
        "order": "desc"
    }
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Suddenly-RP-Model-Builder/1.0"
    }
    
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    
    response = requests.get(url, params=params, headers=headers, timeout=10.0)

    if response.status_code == 403:
        print(f"⚠️  Rate limit GitHub. Utiliser GITHUB_TOKEN environ var.")
        return []

    response.raise_for_status()
    return response.json()


def filter_repos(repos, min_stars=10, created_after=None):
    """Filtrer les repos selon critères."""
    filtered = []
    
    for repo in repos:
        # Filtre étoiles
        if repo.get("stargazers_count", 0) < min_stars:
            continue
        
        # Filtre date
        if created_after:
            created = repo.get("created_at", "")
            if created < created_after:
                continue
        
        # Filtre licences (autorisées + vide = OK)
        license_info = repo.get("license") or {}
        license_type = (license_info.get("spdx_id") or "").lower() if license_info else ""
        if license_type and license_type not in ["mit", "gpl-3.0", "gpl-2.0", "agpl-3.0", "apache-2.0", "unlicense", "cc0-1.0", "cc-by-sa-4.0", "bsd-3-clause", "bsd-2-clause", ""]:
            continue
        
        # Filtre langue (accepter tous, le scan .rpy filtrera après)
        # lang = repo.get("language", "")
        # if lang and lang.lower() not in ["python", "ren'py", ""]:
        #     continue
        
        filtered.append(repo)
    
    return filtered


def scan_rpy_files(repo_full_name, max_files=100):
    """Scanner un repo pour trouver les fichiers .rpy."""
    # recursive=1 est OBLIGATOIRE pour scanner les sous-répertoires
    url = f"https://api.github.com/repos/{repo_full_name}/git/trees/main?recursive=1"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Suddenly-RP-Model-Builder/1.0"
    }
    
    token = get_gh_token()
    if token:
        headers["Authorization"] = f"token {token}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10.0)
        if response.status_code == 404:
            # Essayer master au lieu de main
            url = f"https://api.github.com/repos/{repo_full_name}/git/trees/master"
            response = requests.get(url, headers=headers, timeout=10.0)
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        rpy_files = []
        
        for item in data.get("tree", []):
            if item["path"].endswith(".rpy"):
                rpy_files.append({
                    "path": item["path"],
                    "url": item["url"],
                    "size": item["size"]
                })
        
        return rpy_files[:max_files]
    
    except requests.exceptions.RequestException:
        return []


def discover_repos(max_results=50, min_stars=10, created_after=None):
    """Découvrir les projets Ren'Py sur GitHub."""
    print("🔍 Recherche de projets Ren'Py sur GitHub...")
    
    # Rechercher avec les bons mots-clés : renpy + visualnovel / visual novel
    queries = [
        "renpy visualnovel stars:>10",
        "renpy \"visual novel\" stars:>10",
        "\"visual novel\" language:renpy stars:>10",
        "renpy language:renpy stars:>10",
    ]
    repos = {}
    for q in queries:
        result = search_repositories(q, per_page=100)
        if result and "items" in result:
            existing_names = {r.get("full_name") for r in repos.get("items", [])}
            for item in result["items"]:
                if item.get("full_name") not in existing_names:
                    repos.setdefault("items", []).append(item)
    
    if not repos or "items" not in repos:
        print("⚠️  Aucune recherche n'a donné de résultats, fallback sur 'renpy'...")
        fallback = search_repositories("renpy", per_page=100)
        repos = fallback or {"items": []}
    
    repos = repos.get("items", [])
    print(f"   → {len(repos)} repos trouvés")
    
    # Filtrer
    filtered = filter_repos(repos, min_stars=min_stars, created_after=created_after)
    print(f"   → {len(filtered)} repos après filtrage (étoiles ≥ {min_stars})")
    
    # Scanner les fichiers .rpy
    print("\n📁 Scan des fichiers .rpy...")
    result_repos = []
    
    for i, repo in enumerate(filtered[:max_results]):
        name = repo.get("full_name", "")
        stars = repo.get("stargazers_count", 0)
        
        print(f"   [{i+1}/{max_results}] {name} ({stars} ⭐) — scan .rpy", end="...")
        
        rpy_files = scan_rpy_files(name)
        
        if rpy_files:
            print(f" {len(rpy_files)} fichiers")
            result_repos.append({
                "name": name,
                "url": repo.get("html_url", ""),
                "stars": stars,
                "language": repo.get("language", ""),
                "license": (repo.get("license") or {}).get("name", ""),
                "description": repo.get("description", ""),
                "created_at": repo.get("created_at", ""),
                "updated_at": repo.get("updated_at", ""),
                "rpy_files": rpy_files,
                "total_size_kb": sum(f["size"] for f in rpy_files) / 1024
            })
        else:
            print(" (pas de .rpy)")
        
        # Rate limiting
        time.sleep(0.5)
    
    print(f"\n✅ {len(result_repos)} repos Ren'Py trouvés avec fichiers .rpy")
    return result_repos


def main():
    parser = argparse.ArgumentParser(description="Découvrir projets Ren'Py sur GitHub")
    parser.add_argument("--limit", type=int, default=50, help="Nombre max de résultats")
    parser.add_argument("--min-stars", type=int, default=10, help="Min étoiles")
    parser.add_argument("--since", type=str, default=None, help="Format YYYY-MM-DD")
    parser.add_argument("--output", type=str, default="data/renpy-repos.json", help="Fichier sortie")
    parser.add_argument("--dry-run", action="store_true", help="Mode test sans scan détaillé")
    
    args = parser.parse_args()
    
    if args.since:
        created_after = args.since
    else:
        created_after = None
    
    # Discovery
    repos = discover_repos(
        max_results=args.limit,
        min_stars=args.min_stars,
        created_after=created_after
    )
    
    if not repos:
        print("⚠️  Aucun projet Ren'Py trouvé.")
        return
    
    # Sauvegarde
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(repos, f, indent=2, ensure_ascii=False)
    
    print(f"\n📁 {len(repos)} repos sauvegardés dans {args.output}")
    
    # Statistiques
    total_files = sum(len(r["rpy_files"]) for r in repos)
    total_size = sum(r["total_size_kb"] for r in repos)
    
    print(f"\n📊 Statistiques:")
    print(f"   Total fichiers .rpy : {total_files}")
    print(f"   Taille totale : {total_size:.0f} Ko")
    print(f"   Repos avec > 5 étoiles : {sum(1 for r in repos if r['stars'] > 5)}")


if __name__ == "__main__":
    main()
