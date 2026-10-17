IF DB_ID(N'DemoAim') IS NULL
    CREATE DATABASE DemoAim;
GO

USE DemoAim;
GO

IF OBJECT_ID(N'dbo.Clientes', N'U') IS NOT NULL DROP TABLE dbo.Clientes;
IF OBJECT_ID(N'dbo.Pedidos', N'U') IS NOT NULL DROP TABLE dbo.Pedidos;
GO

CREATE TABLE dbo.Clientes (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    Nombre NVARCHAR(100) NOT NULL,
    Ciudad NVARCHAR(80) NOT NULL,
    Activo BIT NOT NULL DEFAULT 1
);

CREATE TABLE dbo.Pedidos (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    ClienteId INT NOT NULL REFERENCES dbo.Clientes(Id),
    Fecha DATE NOT NULL,
    Total DECIMAL(12,2) NOT NULL
);

INSERT INTO dbo.Clientes (Nombre, Ciudad, Activo) VALUES
(N'Ana Pérez', N'Madrid', 1),
(N'Luis Gómez', N'Barcelona', 1),
(N'María Ruiz', N'Valencia', 0),
(N'Carlos Díaz', N'Sevilla', 1);

INSERT INTO dbo.Pedidos (ClienteId, Fecha, Total) VALUES
(1, '2026-01-10', 120.50),
(1, '2026-02-03', 89.99),
(2, '2026-01-20', 250.00),
(4, '2026-03-01', 45.75);
GO

CREATE OR ALTER PROCEDURE dbo.usp_PedidosPorCliente
    @ClienteId INT
AS
BEGIN
    SET NOCOUNT ON;

    SELECT
        p.Id,
        p.Fecha,
        p.Total,
        c.Nombre AS Cliente,
        c.Ciudad
    FROM dbo.Pedidos p
    INNER JOIN dbo.Clientes c ON c.Id = p.ClienteId
    WHERE p.ClienteId = @ClienteId
    ORDER BY p.Fecha;
END;
GO
