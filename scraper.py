#!/usr/bin/env python3
import os, json, time, random
from datetime import datetime
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, ClientError
from rich.console import Console


console = Console()


class InstagramScraper:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.client = None
        self.current_account = None
        self.total_downloaded = 0
        self.total_errors = 0
    
    def login(self, account):
        username, password = account['username'], account['password']
        self.current_account = username
        try:
            client = Client()
            client.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            session_file = f"sessions/{username}.json"
            
            if os.path.exists(session_file):
                try:
                    client.load_settings(session_file)
                    client.login(username, password)
                    console.print(f"[green]✅ Sessão carregada: @{username}[/green]")
                except:
                    client.login(username, password)
                    os.makedirs("sessions", exist_ok=True)
                    client.dump_settings(session_file)
                    console.print(f"[green]✅ Login: @{username}[/green]")
            else:
                os.makedirs("sessions", exist_ok=True)
                client.login(username, password)
                client.dump_settings(session_file)
                console.print(f"[green]✅ Login: @{username}[/green]")
            
            self.client = client
            return True
        except Exception as e:
            console.print(f"[red]❌ Erro @{username}: {e}[/red]")
            return False
    
    def human_delay(self, min_sec=None, max_sec=None):
        min_sec = min_sec or self.config.get('delay_min', 3)
        max_sec = max_sec or self.config.get('delay_max', 10)
        time.sleep(random.uniform(min_sec, max_sec))
    
    def download_profile(self, username, limit=15, progress=None, task=None):
        try:
            try:
                user_id = self.client.user_id_from_username(username)
            except:
                console.print(f"[red]❌ @{username} não encontrado[/red]")
                return []
            
            medias = self.client.user_medias(user_id, amount=limit)
            if not medias:
                console.print(f"[yellow]⚠️ Sem mídias @{username}[/yellow]")
                return []
            
            profile_folder = f"downloads/{username}"
            os.makedirs(profile_folder, exist_ok=True)
            downloaded = []
            
            for i, media in enumerate(medias, 1):
                if self.db.is_downloaded(media.id):
                    continue
                
                if task and progress:
                    progress.update(task, description=f"[cyan]@{username} ({i}/{len(medias)})")
                
                try:
                    date_str = media.taken_at.strftime("%Y%m%d_%H%M%S")
                    
                    if media.media_type == 1:
                        path = self.client.photo_download(media.id, folder=profile_folder, filename=f"{username}_{date_str}")
                        media_type = 'photo'
                    elif media.media_type == 2:
                        path = self.client.video_download(media.id, folder=profile_folder, filename=f"{username}_{date_str}")
                        media_type = 'video'
                    elif media.media_type == 8:
                        resources = self.client.media_resources(media.id)
                        for j, res in enumerate(resources, 1):
                            try:
                                if res.media_type == 1:
                                    path = self.client.photo_download(res.id, folder=profile_folder, filename=f"{username}_{date_str}_c{j}")
                                    media_type = 'photo'
                                else:
                                    path = self.client.video_download(res.id, folder=profile_folder, filename=f"{username}_{date_str}_c{j}")
                                    media_type = 'video'
                                
                                self.db.add_download({
                                    'media_id': res.id,
                                    'username': username,
                                    'file': os.path.basename(path),
                                    'type': media_type,
                                    'date': media.taken_at.isoformat()
                                })
                                downloaded.append(path)
                                self.total_downloaded += 1
                                self.human_delay(1,3)
                            except:
                                pass
                        continue
                    
                    self.db.add_download({
                        'media_id': media.id,
                        'username': username,
                        'file': os.path.basename(path),
                        'type': media_type,
                        'date': media.taken_at.isoformat()
                    })
                    downloaded.append(path)
                    self.total_downloaded += 1
                    console.print(f"[dim]  ✅ {os.path.basename(path)}[/dim]")
                    
                    if media.media_type == 2 and hasattr(media, 'video_duration'):
                        wait = media.video_duration + random.uniform(2,5)
                        console.print(f"[dim]  🎬 Assistindo {media.video_duration}s...[/dim]")
                        time.sleep(min(wait, 60))
                    else:
                        self.human_delay()
                        
                except PleaseWaitFewMinutes:
                    console.print("[yellow]  ⏳ Esperando 5min...[/yellow]")
                    time.sleep(300)
                except ClientError as e:
                    if "429" in str(e):
                        console.print("[yellow]  ⏳ Rate limit, 2min...[/yellow]")
                        time.sleep(120)
                    else:
                        console.print(f"[red]  ❌ Erro: {e}[/red]")
                        self.total_errors += 1
                except Exception as e:
                    console.print(f"[red]  ❌ Erro: {e}[/red]")
                    self.total_errors += 1
            
            return downloaded
        except Exception as e:
            console.print(f"[red]❌ @{username}: {e}[/red]")
            return []
    
    def scrape_with_account(self, account_index, progress=None, task=None):
        with open('accounts.json', 'r') as f:
            data = json.load(f)
        if account_index >= len(data['accounts']):
            return {'total':0, 'time':0, 'errors':1}
        account = data['accounts'][account_index]
        if not account.get('active', True):
            return {'total':0, 'time':0, 'errors':1}
        if not self.login(account):
            return {'total':0, 'time':0, 'errors':1}
        return self._scrape_all_targets(progress, task)
    
    def scrape_all_accounts(self, progress=None, task=None):
        with open('accounts.json', 'r') as f:
            data = json.load(f)
        total, errors, start = 0, 0, time.time()
        for account in data['accounts']:
            if not account.get('active', True): continue
            if self.login(account):
                result = self._scrape_all_targets(progress, task)
                total += result['total']
                errors += result['errors']
            self.human_delay(10,30)
        return {'total': total, 'time': time.time()-start, 'errors': errors}
    
    def _scrape_all_targets(self, progress=None, task=None):
        with open('targets.json', 'r') as f:
            data = json.load(f)
        total, errors = 0, 0
        targets = sorted(data['targets'], key=lambda x: x.get('priority', 1))
        for target in targets:
            if not target.get('active', True): continue
            console.print(f"\n[bold cyan]🎯 @{target['username']}[/bold cyan]")
            self.human_delay(5,15)
            medias = self.download_profile(
                target['username'],
                limit=self.config.get('posts_per_profile', 15),
                progress=progress,
                task=task
            )
            total += len(medias)
            errors += self.total_errors - errors
        return {'total': total, 'time': 0, 'errors': errors}
