namespace SqlGateway;

public sealed class ConfigForm : Form
{
    private readonly TextBox _sqlServer = new();
    private readonly NumericUpDown _sqlPort = new();
    private readonly TextBox _database = new();
    private readonly TextBox _userId = new();
    private readonly TextBox _password = new();
    private readonly NumericUpDown _listenPort = new();
    private readonly TextBox _apiKey = new();
    private readonly TextBox _listenHost = new();
    private readonly CheckBox _readOnly = new();

    public GatewayOptions Result { get; private set; } = new();

    public ConfigForm(GatewayOptions current)
    {
        Text = "SqlGateway — Configuración";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(460, 560);
        Font = new Font("Segoe UI", 9.75f);

        var y = 18;
        AddLabel("Servidor SQL (host / IP)", y); y += 22;
        Place(_sqlServer, y, 420); y += 36;

        AddLabel("Puerto SQL Server", y); y += 22;
        Place(_sqlPort, y, 120);
        _sqlPort.Minimum = 1;
        _sqlPort.Maximum = 65535;
        y += 36;

        AddLabel("Base de datos", y); y += 22;
        Place(_database, y, 420); y += 36;

        AddLabel("Usuario", y); y += 22;
        Place(_userId, y, 420); y += 36;

        AddLabel("Contraseña", y); y += 22;
        Place(_password, y, 420);
        _password.UseSystemPasswordChar = true;
        y += 36;

        AddLabel("Puerto de escucha del gateway", y); y += 22;
        Place(_listenPort, y, 120);
        _listenPort.Minimum = 1;
        _listenPort.Maximum = 65535;
        y += 36;

        AddLabel("Host de escucha (0.0.0.0 = todas las IPs)", y); y += 22;
        Place(_listenHost, y, 420); y += 36;

        AddLabel("ApiKey (header X-Api-Key; vacío = sin auth)", y); y += 22;
        Place(_apiKey, y, 420); y += 34;

        _readOnly.Text = "Solo lectura (SELECT / EXEC / …)";
        _readOnly.Location = new Point(18, y);
        _readOnly.AutoSize = true;
        Controls.Add(_readOnly);
        y += 40;

        var btnSave = new Button
        {
            Text = "Guardar y cerrar",
            Size = new Size(150, 34),
            Location = new Point(180, y),
            DialogResult = DialogResult.OK
        };
        btnSave.Click += (_, _) =>
        {
            if (!ValidateInputs())
            {
                DialogResult = DialogResult.None;
                return;
            }

            Result = BuildOptions(current);
        };

        var btnCancel = new Button
        {
            Text = "Cancelar",
            Size = new Size(100, 34),
            Location = new Point(340, y),
            DialogResult = DialogResult.Cancel
        };

        AcceptButton = btnSave;
        CancelButton = btnCancel;
        Controls.Add(btnSave);
        Controls.Add(btnCancel);

        LoadFrom(current);
    }

    private void LoadFrom(GatewayOptions o)
    {
        _sqlServer.Text = o.SqlServer;
        _sqlPort.Value = Clamp(o.SqlPort <= 0 ? 1433 : o.SqlPort);
        _database.Text = o.Database;
        _userId.Text = o.UserId;
        _password.Text = o.Password;
        _listenPort.Value = Clamp(o.ListenPort <= 0 ? 5055 : o.ListenPort);
        _listenHost.Text = string.IsNullOrWhiteSpace(o.ListenHost) ? "0.0.0.0" : o.ListenHost;
        _apiKey.Text = o.ApiKey;
        _readOnly.Checked = o.ReadOnlyMode;
    }

    private GatewayOptions BuildOptions(GatewayOptions current)
    {
        var o = new GatewayOptions();
        o.CopyFrom(current);
        o.SqlServer = _sqlServer.Text.Trim();
        o.SqlPort = (int)_sqlPort.Value;
        o.Database = _database.Text.Trim();
        o.UserId = _userId.Text.Trim();
        o.Password = _password.Text;
        o.ListenPort = (int)_listenPort.Value;
        o.ListenHost = _listenHost.Text.Trim();
        o.ApiKey = _apiKey.Text;
        o.ReadOnlyMode = _readOnly.Checked;
        o.ConnectionString = string.Empty;
        return o;
    }

    private bool ValidateInputs()
    {
        if (string.IsNullOrWhiteSpace(_sqlServer.Text))
        {
            MessageBox.Show(this, "Indique el servidor SQL.", "Validación", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }

        if (string.IsNullOrWhiteSpace(_listenHost.Text))
        {
            MessageBox.Show(this, "Indique el host de escucha.", "Validación", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return false;
        }

        return true;
    }

    private void AddLabel(string text, int y)
    {
        Controls.Add(new Label
        {
            Text = text,
            AutoSize = true,
            Location = new Point(18, y)
        });
    }

    private void Place(Control c, int y, int width)
    {
        c.Location = new Point(18, y);
        c.Width = width;
        Controls.Add(c);
    }

    private static decimal Clamp(int value) => Math.Clamp(value, 1, 65535);
}
