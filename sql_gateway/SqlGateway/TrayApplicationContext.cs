using System.Diagnostics;

namespace SqlGateway;

public sealed class TrayApplicationContext : ApplicationContext
{
    private readonly NotifyIcon _tray;
    private readonly GatewayOptions _liveOptions;
    private readonly Func<Task> _stopHostAsync;
    private ConfigForm? _openForm;

    public TrayApplicationContext(GatewayOptions liveOptions, Func<Task> stopHostAsync)
    {
        _liveOptions = liveOptions;
        _stopHostAsync = stopHostAsync;

        var menu = new ContextMenuStrip();
        menu.Items.Add("Configuración…", null, (_, _) => ShowConfig());
        menu.Items.Add("Abrir /health en el navegador", null, (_, _) => OpenHealth());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Salir", null, async (_, _) => await ExitAsync());

        _tray = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Visible = true,
            Text = $"SqlGateway :{liveOptions.ListenPort}",
            ContextMenuStrip = menu
        };
        _tray.DoubleClick += (_, _) => ShowConfig();

        _tray.ShowBalloonTip(
            3000,
            "SqlGateway",
            $"Escuchando en el puerto {liveOptions.ListenPort}. Doble clic en el icono para configurar.",
            ToolTipIcon.Info);
    }

    public void ShowConfig()
    {
        if (_openForm is { IsDisposed: false })
        {
            _openForm.Activate();
            return;
        }

        using var form = new ConfigForm(Clone(_liveOptions));
        _openForm = form;
        var result = form.ShowDialog();
        _openForm = null;

        if (result != DialogResult.OK)
        {
            return;
        }

        var previousPort = _liveOptions.ListenPort;
        var previousHost = _liveOptions.ListenHost;

        _liveOptions.CopyFrom(form.Result);
        SettingsService.Save(_liveOptions);
        _tray.Text = $"SqlGateway :{_liveOptions.ListenPort}";

        var listenChanged = previousPort != _liveOptions.ListenPort
            || !string.Equals(previousHost, _liveOptions.ListenHost, StringComparison.OrdinalIgnoreCase);

        if (listenChanged)
        {
            MessageBox.Show(
                "Se cambió el puerto/host de escucha.\nLa aplicación se reiniciará para aplicar el cambio.",
                "SqlGateway",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            RestartProcess();
            return;
        }

        _tray.ShowBalloonTip(2500, "SqlGateway", "Configuración guardada. El servicio sigue activo.", ToolTipIcon.Info);
    }

    private void OpenHealth()
    {
        var host = _liveOptions.ListenHost is "0.0.0.0" or "::" ? "127.0.0.1" : _liveOptions.ListenHost;
        var url = $"http://{host}:{_liveOptions.ListenPort}/health";
        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    }

    private async Task ExitAsync()
    {
        _tray.Visible = false;
        try
        {
            await _stopHostAsync();
        }
        catch
        {
            // ignore
        }

        ExitThread();
    }

    private void RestartProcess()
    {
        var path = Environment.ProcessPath;
        if (!string.IsNullOrEmpty(path))
        {
            Process.Start(new ProcessStartInfo(path)
            {
                WorkingDirectory = AppContext.BaseDirectory,
                UseShellExecute = true
            });
        }

        _ = ExitAsync();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _tray.Dispose();
        }

        base.Dispose(disposing);
    }

    private static GatewayOptions Clone(GatewayOptions source)
    {
        var copy = new GatewayOptions();
        copy.CopyFrom(source);
        return copy;
    }
}
