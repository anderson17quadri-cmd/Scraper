#!/usr/bin/env python3
import os, sys, json, time, argparse
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn
from rich.prompt import Prompt, Confirm
from rich.box import ROUNDED
from rich.layout import Layout
from rich.live import Live
from scraper import InstagramScraper
from database import DownloadDB
from utils import setup_logging, load_config, get_system_info
from dashboard import Dashboard


console = Console()
logger = setup_logging()


class IGScraperPro:
    def __init__(self):
        self.config = load_config()
        self.db = DownloadDB()
        self.scraper = InstagramScraper(self.config, self.db)
        self.running = True
        os.makedirs("downloads", exist_ok=True)
        os.makedirs("sessions", exist_ok=True)
        os.makedirs("logs", exist_ok=True)
        os.makedirs("backups", exist_ok=True)
        self._init_default_files()
    
    def _init_default_files(self):
        if not os.path.exists("accounts.json"):
            with open("accounts.json", "w") as f:
                json.dump({"accounts": []}, f, indent=2)
        if not os.path.exists("targets.json"):
            with open("targets.json", "w") as f:
                json.dump({"targets": []}, f, indent=2)
        if not os.path.exists("config.json"):
            default_config = {
                "delay_min": 3, "delay_max": 10, "posts_per_profile": 15,
                "max_retries": 3, "session_timeout": 3600, "log_level": "INFO",
                "auto_mode": False, "auto_interval": 3600, "max_downloads_per_day": 500
            }
            with open("config.json", "w") as f:
                json.dump(default_config, f, indent=2)
    
    def show_banner(self):
        sys_info = get_system_info()
        banner = f"""
╔═══════════════════════════════════════════════════════════╗
║  📸  IG-SCRAPER-PRO  v2.0                               ║
║  🚀  Scraper humano com Dashboard                      ║
║  🔐  Login pela própria interface                      ║
║                                                          ║
║  📱  {sys_info['device']}                               ║
║  💾  {sys_info['storage']}                              ║
║  📊  {sys_info['downloads']} mídias baixadas           ║
╚═══════════════════════════════════════════════════════════╝
"""
        console.print(Panel(banner, style="bold cyan", border_style="bright_blue"))
    
    def show_menu(self):
        self.show_banner()
        stats = self.db.get_stats()
        info_table = Table(show_header=False, box=None, style="dim")
        info_table.add_column("", style="bold yellow")
        info_table.add_column("", style="white")
        info_table.add_row("📁 Total baixado:", f"[bold bright_green]{stats['total']:,}[/bold bright_green]")
        info_table.add_row("👤 Perfis scrapados:", f"[bold bright_cyan]{stats['profiles']}[/bold bright_cyan]")
        info_table.add_row("💾 Espaço usado:", f"[bold bright_magenta]{stats['disk_usage']}[/bold bright_magenta]")
        info_table.add_row("🕐 Último download:", stats['last_download'] or "[dim]Nunca[/dim]")
        console.print(info_table)
        console.print("\n")
        
        menu_table = Table(show_header=False, box=None, padding=(0, 2))
        menu_table.add_column("", style="bold bright_blue")
        menu_table.add_column("", style="white")
        menu_items = [
            ("1", "▶️  Iniciar scraping (todas contas)"),
            ("2", "▶️  Scraping com conta específica"),
            ("3", "📊  Dashboard interativa (com login)"),
            ("4", "📝  Gerenciar contas"),
            ("5", "🎯  Gerenciar perfis alvo"),
            ("6", "📁  Ver downloads recentes"),
            ("7", "🧹  Limpar cache"),
            ("8", "🔄  Rodar em modo automático"),
            ("0", "🚪  Sair")
        ]
        for item in menu_items:
            menu_table.add_row(*item)
        console.print(menu_table)
        console.print("\n[dim]💡 Use Ctrl+C para interromper[/dim]")
        return Prompt.ask("\n[bold green]Escolha uma opção[/bold green]", choices=["0","1","2","3","4","5","6","7","8"])
    
    def run_scraping(self, account_index=None, auto_mode=False):
        if auto_mode:
            console.print("[bold cyan]🤖 Modo automático ativado[/bold cyan]")
        
        with open('accounts.json', 'r') as f:
            accounts_data = json.load(f)
        if not accounts_data.get('accounts'):
            console.print("[bold red]❌ Nenhuma conta cadastrada![/bold red]")
            console.print("[yellow]Use a Dashboard ou o menu para adicionar.[/yellow]")
            return {'total': 0, 'errors': 1}
        
        with open('targets.json', 'r') as f:
            targets_data = json.load(f)
        if not targets_data.get('targets'):
            console.print("[bold red]❌ Nenhum perfil alvo cadastrado![/bold red]")
            console.print("[yellow]Use a Dashboard ou o menu para adicionar.[/yellow]")
            return {'total': 0, 'errors': 1}
        
        start_time = time.time()
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                     BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                     TimeRemainingColumn(), console=console) as progress:
            task = progress.add_task("[cyan]Iniciando scraping...", total=100)
            try:
                if account_index is not None:
                    result = self.scraper.scrape_with_account(account_index, progress, task)
                else:
                    result = self.scraper.scrape_all_accounts(progress, task)
                elapsed = time.time() - start_time
                console.print("\n[bold green]✅ SCRAPING CONCLUÍDO![/bold green]")
                console.print(f"📊 Total baixado: [bold yellow]{result['total']}[/bold yellow]")
                console.print(f"⏱️  Tempo: [bold yellow]{elapsed:.1f}s[/bold yellow]")
                console.print(f"⚠️  Erros: [bold yellow]{result['errors']}[/bold yellow]")
                return result
            except KeyboardInterrupt:
                console.print("\n[yellow]⏹️ Interrompido[/yellow]")
                return {'total': 0, 'errors': 1}
    
    def show_dashboard(self):
        dashboard = Dashboard()
        dashboard.run()
    
    def manage_accounts(self):
        console.print("\n[bold cyan]📝 GERENCIAR CONTAS[/bold cyan]\n")
        with open('accounts.json', 'r') as f:
            data = json.load(f)
        if data['accounts']:
            table = Table(title="Contas", style="bright_blue", box=ROUNDED)
            table.add_column("#", style="bold yellow")
            table.add_column("Usuário", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Downloads", style="white")
            table.add_column("Último uso", style="dim")
            for i, acc in enumerate(data['accounts'], 1):
                status = "🟢 Ativa" if acc.get('active', True) else "🔴 Inativa"
                downloads = self.db.get_account_downloads(acc['username'])
                last = acc.get('last_use', 'Nunca')[:16]
                table.add_row(str(i), f"@{acc['username']}", status, str(downloads), last)
            console.print(table)
            console.print("\n[dim]A-Adicionar | D-Desativar | R-Remover | L-Login[/dim]")
            action = Prompt.ask("[green]Ação[/green]", choices=["A","D","R","L","C"], default="C")
            if action == "A":
                username = Prompt.ask("[cyan]Usuário[/cyan]")
                password = Prompt.ask("[cyan]Senha[/cyan]", password=True)
                data['accounts'].append({"username": username, "password": password, "active": True, "created_at": datetime.now().isoformat(), "last_use": None})
                with open('accounts.json', 'w') as f: json.dump(data, f, indent=2)
                console.print("[bold green]✅ Conta adicionada![/bold green]")
            elif action == "D":
                idx = int(Prompt.ask("[cyan]Número[/cyan]")) - 1
                if 0 <= idx < len(data['accounts']):
                    data['accounts'][idx]['active'] = False
                    with open('accounts.json', 'w') as f: json.dump(data, f, indent=2)
                    console.print("[bold green]✅ Conta desativada![/bold green]")
            elif action == "R":
                idx = int(Prompt.ask("[cyan]Número[/cyan]")) - 1
                if 0 <= idx < len(data['accounts']):
                    del data['accounts'][idx]
                    with open('accounts.json', 'w') as f: json.dump(data, f, indent=2)
                    console.print("[bold green]✅ Conta removida![/bold green]")
            elif action == "L":
                idx = int(Prompt.ask("[cyan]Número da conta para login[/cyan]")) - 1
                if 0 <= idx < len(data['accounts']):
                    console.print("[yellow]Testando login...[/yellow]")
                    if self.scraper.login(data['accounts'][idx]):
                        data['accounts'][idx]['last_use'] = datetime.now().isoformat()
                        with open('accounts.json', 'w') as f: json.dump(data, f, indent=2)
                        console.print("[bold green]✅ Login testado e aprovado![/bold green]")
                    else:
                        console.print("[bold red]❌ Falha no login![/bold red]")
        else:
            console.print("[yellow]Nenhuma conta cadastrada.[/yellow]")
            if Confirm.ask("[green]Adicionar agora?[/green]"):
                username = Prompt.ask("[cyan]Usuário[/cyan]")
                password = Prompt.ask("[cyan]Senha[/cyan]", password=True)
                data['accounts'].append({"username": username, "password": password, "active": True, "created_at": datetime.now().isoformat(), "last_use": None})
                with open('accounts.json', 'w') as f: json.dump(data, f, indent=2)
                console.print("[bold green]✅ Conta adicionada![/bold green]")
    
    def manage_targets(self):
        console.print("\n[bold cyan]🎯 GERENCIAR PERFIS[/bold cyan]\n")
        with open('targets.json', 'r') as f:
            data = json.load(f)
        if data['targets']:
            table = Table(title="Perfis", style="bright_blue", box=ROUNDED)
            table.add_column("#", style="bold yellow")
            table.add_column("Perfil", style="cyan")
            table.add_column("Prioridade", style="white")
            table.add_column("Status", style="green")
            table.add_column("Adicionado", style="dim")
            for i, target in enumerate(data['targets'], 1):
                status = "🟢 Ativo" if target.get('active', True) else "🔴 Inativo"
                priority = "⭐" * target.get('priority', 1)
                added = target.get('added_at', 'N/A')[:16]
                table.add_row(str(i), f"@{target['username']}", priority, status, added)
            console.print(table)
            console.print("\n[dim]A-Adicionar | D-Desativar | R-Remover[/dim]")
            action = Prompt.ask("[green]Ação[/green]", choices=["A","D","R","C"], default="C")
            if action == "A":
                username = Prompt.ask("[cyan]Usuário (sem @)[/cyan]")
                priority = int(Prompt.ask("[cyan]Prioridade (1-5)[/cyan]", default="1"))
                data['targets'].append({"username": username, "priority": priority, "active": True, "added_at": datetime.now().isoformat()})
                with open('targets.json', 'w') as f: json.dump(data, f, indent=2)
                console.print("[bold green]✅ Perfil adicionado![/bold green]")
            elif action == "D":
                idx = int(Prompt.ask("[cyan]Número[/cyan]")) - 1
                if 0 <= idx < len(data['targets']):
                    data['targets'][idx]['active'] = False
                    with open('targets.json', 'w') as f: json.dump(data, f, indent=2)
                    console.print("[bold green]✅ Perfil desativado![/bold green]")
            elif action == "R":
                idx = int(Prompt.ask("[cyan]Número[/cyan]")) - 1
                if 0 <= idx < len(data['targets']):
                    del data['targets'][idx]
                    with open('targets.json', 'w') as f: json.dump(data, f, indent=2)
                    console.print("[bold green]✅ Perfil removido![/bold green]")
        else:
            console.print("[yellow]Nenhum perfil cadastrado.[/yellow]")
            if Confirm.ask("[green]Adicionar agora?[/green]"):
                username = Prompt.ask("[cyan]Usuário (sem @)[/cyan]")
                priority = int(Prompt.ask("[cyan]Prioridade (1-5)[/cyan]", default="1"))
                data['targets'].append({"username": username, "priority": priority, "active": True, "added_at": datetime.now().isoformat()})
                with open('targets.json', 'w') as f: json.dump(data, f, indent=2)
                console.print("[bold green]✅ Perfil adicionado![/bold green]")
    
    def show_recent_downloads(self):
        console.print("\n[bold cyan]📁 DOWNLOADS RECENTES[/bold cyan]\n")
        recent = self.db.get_recent_downloads(limit=20)
        if not recent:
            console.print("[yellow]Nenhum download realizado ainda.[/yellow]")
            return
        table = Table(title=f"Últimos {len(recent)} downloads", style="bright_blue", box=ROUNDED)
        table.add_column("Arquivo", style="cyan")
        table.add_column("Perfil", style="yellow")
        table.add_column("Tipo", style="green")
        table.add_column("Data", style="dim")
        for item in recent:
            file_name = item['file'][:20] + "..." if len(item['file']) > 20 else item['file']
            media_type = "📷" if item.get('type') == 'photo' else "🎬"
            table.add_row(file_name, f"@{item['profile']}", media_type, item['date'][:16])
        console.print(table)
    
    def clear_cache(self):
        if Confirm.ask("[red]Limpar cache? Isso remove logs antigos.[/red]"):
            self.db.clear_cache()
            console.print("[bold green]✅ Cache limpo![/bold green]")
    
    def run_auto_mode(self):
        interval = self.config.get('auto_interval', 3600)
        console.print(f"\n[bold cyan]🔄 MODO AUTOMÁTICO[/bold cyan]\n[green]⏱️  Intervalo: {interval//60}min[/green]\n[dim]Ctrl+C para parar[/dim]")
        try:
            while True:
                console.print(f"\n[bold yellow]▶️  Ciclo {datetime.now().strftime('%H:%M:%S')}[/bold yellow]")
                self.run_scraping(auto_mode=True)
                console.print(f"\n[dim]⏳ Aguardando {interval//60}min...[/dim]")
                time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[yellow]⏹️ Modo automático parado[/yellow]")
    
    def run(self):
        while self.running:
            try:
                choice = self.show_menu()
                if choice == "0":
                    console.print("\n[bold yellow]👋 Até logo![/bold yellow]")
                    self.running = False
                    break
                elif choice == "1":
                    self.run_scraping()
                elif choice == "2":
                    with open('accounts.json', 'r') as f:
                        data = json.load(f)
                    if data['accounts']:
                        console.print("\n[cyan]Contas disponíveis:[/cyan]")
                        for i, acc in enumerate(data['accounts'], 1):
                            status = "✅" if acc.get('active', True) else "❌"
                            console.print(f"  {status} [{i}] @{acc['username']}")
                        idx = int(Prompt.ask("[green]Qual conta usar?[/green]", default="1")) - 1
                        if 0 <= idx < len(data['accounts']):
                            self.run_scraping(account_index=idx)
                    else:
                        console.print("[red]❌ Nenhuma conta cadastrada![/red]")
                elif choice == "3":
                    self.show_dashboard()
                elif choice == "4":
                    self.manage_accounts()
                elif choice == "5":
                    self.manage_targets()
                elif choice == "6":
                    self.show_recent_downloads()
                elif choice == "7":
                    self.clear_cache()
                elif choice == "8":
                    self.run_auto_mode()
                if choice != "0" and choice != "3":
                    Prompt.ask("\n[dim]Enter para continuar...[/dim]")
                    os.system('clear')
            except KeyboardInterrupt:
                console.print("\n[yellow]⏹️ Interrompido[/yellow]")
                continue
            except Exception as e:
                console.print(f"[bold red]❌ Erro: {e}[/bold red]")
                continue


if __name__ == "__main__":
    try:
        IGScraperPro().run()
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Até logo![/yellow]")
        sys.exit(0)
