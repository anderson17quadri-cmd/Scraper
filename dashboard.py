#!/usr/bin/env python3
import os, sys, time, json, shutil
from datetime import datetime
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.align import Align
from rich.box import ROUNDED
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from database import DownloadDB
from utils import get_system_info, get_top_profiles, get_downloads_by_day, get_performance_stats
from scraper import InstagramScraper


console = Console()


class Dashboard:
    def __init__(self):
        self.db = DownloadDB()
        self.scraper = InstagramScraper({}, self.db)
        self.running = True
        self.refresh_rate = 5
        self.current_account = None
        self.logged_in = False
    
    def show_login_panel(self):
        console.clear()
        
        login_panel = Panel(
            """
[bold bright_cyan]🔐 LOGIN NO INSTAGRAM[/bold bright_cyan]


[dim]Faça login com uma conta para começar a baixar.[/dim]


[bold yellow]⚠️  IMPORTANTE:[/bold yellow]
• Use contas descartáveis
• Não use sua conta principal
• O scraper simula comportamento humano
• Risco de ban é mínimo com os delays


[green]Pressione Enter para começar...[/green]
            """,
            title="📸 Login",
            border_style="bright_blue",
            box=ROUNDED,
            padding=(2,4)
        )
        console.print(login_panel)
        Prompt.ask("")
        
        with open('accounts.json', 'r') as f:
            data = json.load(f)
        
        if data['accounts']:
            console.print("\n[bold cyan]📋 Contas salvas:[/bold cyan]")
            table = Table(show_header=True, box=ROUNDED)
            table.add_column("#", style="bold yellow")
            table.add_column("Usuário", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Último uso", style="dim")
            
            for i, acc in enumerate(data['accounts'], 1):
                status = "🟢 Ativa" if acc.get('active', True) else "🔴 Inativa"
                last = acc.get('last_use', 'Nunca')[:16]
                table.add_row(str(i), f"@{acc['username']}", status, last)
            
            console.print(table)
            
            choice = Prompt.ask("\n[green]Usar conta salva ou adicionar nova?[/green]", 
                               choices=["s","n","c"], default="s")
            
            if choice == "s":
                idx = int(Prompt.ask("[cyan]Número da conta[/cyan]", default="1")) - 1
                if 0 <= idx < len(data['accounts']):
                    account = data['accounts'][idx]
                    if account.get('active', True):
                        self.current_account = account
                        self._test_login()
                        if self.logged_in:
                            return True
                        else:
                            console.print("[red]❌ Falha no login. Tente novamente.[/red]")
                            time.sleep(2)
                    else:
                        console.print("[yellow]⚠️ Conta desativada. Ative no menu principal.[/yellow]")
            
            elif choice == "n":
                return self._add_new_account()
            
            else:
                return self._add_new_account()
        else:
            console.print("[yellow]Nenhuma conta salva.[/yellow]")
            return self._add_new_account()
        
        return False
    
    def _add_new_account(self):
        console.print("\n[bold cyan]➕ ADICIONAR NOVA CONTA[/bold cyan]")
        username = Prompt.ask("[cyan]Usuário[/cyan]")
        password = Prompt.ask("[cyan]Senha[/cyan]", password=True)
        
        with open('accounts.json', 'r') as f:
            data = json.load(f)
        
        data['accounts'].append({
            "username": username,
            "password": password,
            "active": True,
            "created_at": datetime.now().isoformat(),
            "last_use": None
        })
        
        with open('accounts.json', 'w') as f:
            json.dump(data, f, indent=2)
        
        self.current_account = data['accounts'][-1]
        self._test_login()
        return self.logged_in
    
    def _test_login(self):
        console.print("[yellow]🔐 Testando login...[/yellow]")
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), 
                     console=console) as progress:
            task = progress.add_task("[cyan]Autenticando...", total=None)
            
            if self.scraper.login(self.current_account):
                self.logged_in = True
                progress.update(task, description="[green]✅ Login bem sucedido!")
                time.sleep(0.5)
                
                with open('accounts.json', 'r') as f:
                    data = json.load(f)
                for acc in data['accounts']:
                    if acc['username'] == self.current_account['username']:
                        acc['last_use'] = datetime.now().isoformat()
                        break
                with open('accounts.json', 'w') as f:
                    json.dump(data, f, indent=2)
                
                return True
            else:
                self.logged_in = False
                progress.update(task, description="[red]❌ Falha no login!")
                time.sleep(0.5)
                return False
    
    def create_login_layout(self):
        layout = Layout()
        layout.split(Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=1))
        
        header = Text()
        header.append("📸 IG-SCRAPER-PRO", style="bold bright_cyan")
        header.append(" • ", style="dim")
        header.append("Dashboard com Login", style="bright_yellow")
        layout["header"].update(Align.center(header))
        
        login_msg = """
[bold bright_cyan]🔐 Faça login para continuar[/bold bright_cyan]


[dim]Use uma conta descartável do Instagram.[/dim]


[green]Pressione Ctrl+C a qualquer momento para sair.[/green]
        """
        layout["body"].update(Panel(login_msg, border_style="bright_blue", box=ROUNDED, padding=(3,5)))
        
        with open('accounts.json', 'r') as f:
            data = json.load(f)
        
        if data['accounts']:
            table = Table(show_header=True, box=ROUNDED)
            table.add_column("#", style="bold yellow")
            table.add_column("Usuário", style="cyan")
            table.add_column("Status", style="green")
            for i, acc in enumerate(data['accounts'], 1):
                status = "🟢" if acc.get('active', True) else "🔴"
                table.add_row(str(i), f"@{acc['username']}", status)
            
            layout["body"].update(Panel(table, title="📋 Contas Salvas", border_style="bright_yellow", box=ROUNDED))
        
        layout["footer"].update(Align.center(Text("Ctrl+C para sair", style="dim")))
        return layout
    
    def create_header(self):
        header = Text()
        header.append("📸 IG-SCRAPER-PRO", style="bold bright_cyan")
        header.append(" • ", style="dim")
        header.append("Dashboard v2.0", style="bright_yellow")
        header.append(" • ", style="dim")
        
        if self.logged_in and self.current_account:
            header.append(f"👤 @{self.current_account['username']}", style="bright_green")
            header.append(" 🟢", style="bright_green")
        else:
            header.append("🔴 Desconectado", style="bright_red")
        
        header.append(" • ", style="dim")
        header.append(datetime.now().strftime("%H:%M:%S"), style="bright_blue")
        
        return Align.center(header)
    
    def create_stats_panel(self, stats):
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("", style="bold cyan")
        table.add_column("", style="bold white")
        table.add_row("📁 Total Downloads", f"[bold bright_green]{stats['total']:,}[/bold bright_green]")
        table.add_row("👤 Perfis Scrapados", f"[bold bright_yellow]{stats['profiles']}[/bold bright_yellow]")
        table.add_row("💾 Espaço em Disco", f"[bold bright_blue]{stats['disk_usage']}[/bold bright_blue]")
        
        if stats['last_download']:
            last = datetime.fromisoformat(stats['last_download'])
            diff = datetime.now() - last
            if diff.days > 0: time_str = f"{diff.days}d atrás"
            elif diff.seconds > 3600: time_str = f"{diff.seconds//3600}h atrás"
            elif diff.seconds > 60: time_str = f"{diff.seconds//60}m atrás"
            else: time_str = "agora"
            table.add_row("🕐 Último Download", f"[dim]{time_str}[/dim]")
        else:
            table.add_row("🕐 Último Download", "[dim]Nunca[/dim]")
        
        perf_stats = get_performance_stats()
        if perf_stats['avg_per_hour'] > 0:
            table.add_row("⚡ Velocidade", f"[bright_magenta]{perf_stats['avg_per_hour']}/hora[/bright_magenta]")
        
        if self.logged_in:
            table.add_row("🔐 Status", "[bright_green]Conectado[/bright_green]")
        else:
            table.add_row("🔐 Status", "[bright_red]Desconectado[/bright_red]")
        
        return Panel(table, title="📊 Estatísticas", border_style="bright_blue", box=ROUNDED, padding=(1,2))
    
    def create_profiles_table(self, profiles):
        if not profiles:
            return Panel("[dim]Nenhum perfil[/dim]", title="🏆 Top Perfis", border_style="bright_yellow", box=ROUNDED)
        
        table = Table(show_header=True, box=None, padding=(0,1))
        table.add_column("Rank", style="bold yellow", width=6)
        table.add_column("Perfil", style="cyan", width=20)
        table.add_column("Downloads", style="bright_green", justify="right", width=12)
        table.add_column("Progresso", style="white", width=20)
        
        max_downloads = max([p['count'] for p in profiles]) if profiles else 1
        for i, profile in enumerate(profiles[:10], 1):
            percentage = (profile['count'] / max_downloads) * 100 if max_downloads > 0 else 0
            bar_length = 15
            filled = int((percentage / 100) * bar_length)
            bar = "█" * filled + "░" * (bar_length - filled)
            rank = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"#{i}"
            table.add_row(rank, f"@{profile['username']}", str(profile['count']), bar)
        
        return Panel(table, title="🏆 Top Perfis", border_style="bright_yellow", box=ROUNDED)
    
    def create_activity_chart(self, days_data):
        if not days_data:
            return Panel("[dim]Sem atividade[/dim]", title="📈 Atividade", border_style="bright_magenta", box=ROUNDED)
        
        days = sorted(days_data.keys())[-7:] if len(days_data) > 7 else sorted(days_data.keys())
        values = [days_data[d] for d in days]
        max_val = max(values) if values else 1
        chart_lines = []
        
        for i, day in enumerate(days):
            day_name = datetime.strptime(day, "%Y-%m-%d").strftime("%a")
            percentage = (values[i] / max_val) * 100 if max_val > 0 else 0
            bar_length = int((percentage / 100) * 20)
            bar = "█" * bar_length + "░" * (20 - bar_length)
            color = "bright_green" if percentage > 80 else "bright_yellow" if percentage > 50 else "bright_red"
            chart_lines.append(f"{day_name} {bar} [bold {color}]{values[i]}[/bold {color}]")
        
        return Panel("\n".join(chart_lines), title="📈 Atividade por Dia", border_style="bright_magenta", box=ROUNDED)
    
    def create_recent_panel(self, recent):
        if not recent:
            return Panel("[dim]Nenhum recente[/dim]", title="📁 Recentes", border_style="bright_cyan", box=ROUNDED)
        
        table = Table(show_header=True, box=None, padding=(0,1))
        table.add_column("Arquivo", style="cyan", width=20)
        table.add_column("Perfil", style="yellow", width=15)
        table.add_column("Tipo", style="green", width=8)
        table.add_column("Hora", style="dim", width=8)
        
        for item in recent[:5]:
            file_name = item['file'][:18] + "..." if len(item['file']) > 18 else item['file']
            media_type = "📷" if item.get('type') == 'photo' else "🎬"
            hour = item['date'][11:16] if len(item['date']) > 16 else item['date']
            table.add_row(file_name, f"@{item['profile']}", media_type, hour)
        
        return Panel(table, title="📁 Downloads Recentes", border_style="bright_cyan", box=ROUNDED)
    
    def create_system_info(self):
        sys_info = get_system_info()
        table = Table(show_header=False, box=None, padding=(0,1))
        table.add_column("", style="bold yellow")
        table.add_column("", style="white")
        table.add_row("📱 Dispositivo", sys_info['device'])
        table.add_row("💾 Armazenamento", sys_info['storage'])
        table.add_row("📊 Total", f"{sys_info['downloads']} mídias")
        
        if self.current_account:
            table.add_row("👤 Conta", f"@{self.current_account['username']}")
        
        return Panel(table, title="💻 Sistema", border_style="bright_cyan", box=ROUNDED)
    
    def create_action_panel(self):
        actions = []
        
        if self.logged_in:
            actions.append("[bold green]▶️  [1] Iniciar Scraping[/bold green]")
            actions.append("[bold yellow]🔄 [2] Trocar Conta[/bold yellow]")
        else:
            actions.append("[bold red]🔐 [1] Fazer Login[/bold red]")
        
        actions.append("[bold cyan]📊 [3] Atualizar Dados[/bold cyan]")
        actions.append("[dim]📝 [4] Gerenciar Targets[/dim]")
        actions.append("[dim]🧹 [5] Limpar Cache[/dim]")
        actions.append("[red]🚪 [0] Sair[/red]")
        
        return Panel("\n".join(actions), title="⚡ Ações Rápidas", border_style="bright_green", box=ROUNDED)
    
    def create_layout(self):
        layout = Layout()
        layout.split(Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=1))
        layout["body"].split_row(Layout(name="left", ratio=2), Layout(name="right", ratio=1))
        layout["left"].split(Layout(name="stats", size=7), Layout(name="charts", size=9), Layout(name="recent", size=7))
        layout["right"].split(Layout(name="profiles", size=12), Layout(name="system", size=6), Layout(name="actions", size=6))
        
        stats = self.db.get_stats()
        profiles = get_top_profiles()
        days_data = get_downloads_by_day()
        recent = self.db.get_recent_downloads(limit=10)
        
        layout["header"].update(self.create_header())
        layout["stats"].update(self.create_stats_panel(stats))
        layout["charts"].update(self.create_activity_chart(days_data))
        layout["recent"].update(self.create_recent_panel(recent))
        layout["profiles"].update(self.create_profiles_table(profiles))
        layout["system"].update(self.create_system_info())
        layout["actions"].update(self.create_action_panel())
        layout["footer"].update(Align.center(Text("Pressione um número para ação | Ctrl+C para sair", style="dim")))
        
        return layout
    
    def handle_action(self, action):
        if action == "1":
            if self.logged_in:
                console.print("[bold green]▶️  Iniciando scraping...[/bold green]")
                from main import IGScraperPro
                app = IGScraperPro()
                app.scraper = self.scraper
                app.run_scraping(account_index=0)
            else:
                console.print("[yellow]🔐 Faça login primeiro![/yellow]")
                time.sleep(1)
                return self.run()
        
        elif action == "2":
            if self.logged_in:
                self.logged_in = False
                self.current_account = None
                console.print("[yellow]🔄 Desconectado. Faça login novamente.[/yellow]")
                time.sleep(0.5)
                return self.run()
            else:
                return self.run()
        
        elif action == "3":
            console.print("[cyan]🔄 Atualizando dados...[/cyan]")
            time.sleep(0.3)
        
        elif action == "4":
            console.print("[cyan]📝 Gerenciar Targets...[/cyan]")
            from main import IGScraperPro
            app = IGScraperPro()
            app.manage_targets()
            time.sleep(1)
        
        elif action == "5":
            from main import IGScraperPro
            app = IGScraperPro()
            app.clear_cache()
            time.sleep(1)
        
        elif action == "0":
            self.running = False
            return False
        
        return True
    
    def run(self):
        console.clear()
        
        if not self.logged_in:
            self.show_login_panel()
        
        if not self.logged_in:
            console.print("[red]❌ Login necessário para usar o dashboard.[/red]")
            time.sleep(2)
            return
        
        with Live(self.create_layout(), refresh_per_second=1, screen=True) as live:
            try:
                while self.running:
                    time.sleep(0.5)
                    live.update(self.create_layout())
                    
                    if console.is_terminal:
                        import select
                        import sys
                        if select.select([sys.stdin], [], [], 0)[0]:
                            key = sys.stdin.read(1)
                            if key in ['1','2','3','4','5','0']:
                                live.update(self.create_layout())
                                self.handle_action(key)
                                if not self.running:
                                    break
                                
            except KeyboardInterrupt:
                self.running = False
                console.print("\n[yellow]Dashboard encerrado[/yellow]")
                time.sleep(0.5)


if __name__ == "__main__":
    dashboard = Dashboard()
    dashboard.run()
