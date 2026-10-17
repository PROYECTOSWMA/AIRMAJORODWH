
from __future__ import annotations

from peewee import CharField, DecimalField

from assets.static_data_asset.models.base import BaseModel


class StaticPayroll(BaseModel):

    class Meta:
        table_name = "static_payroll"

    # Réplica de las columnas con cabecera de la hoja, normalizadas con ``to_db_field``.
    periodo = CharField(null=True)
    mes = CharField(null=True)
    pivot = CharField(null=True)
    fecha = CharField(null=True)
    tipo = CharField(null=True)
    dni = CharField(null=True)
    codigo = CharField(null=True)
    nombre = CharField(null=True)
    oficina = CharField(null=True)
    cargo = CharField(null=True)
    area = CharField(null=True)
    remuner = DecimalField(max_digits=18, decimal_places=2, null=True)
    tc = DecimalField(max_digits=18, decimal_places=4, null=True)
    dias = DecimalField(max_digits=18, decimal_places=2, null=True)
    monpago = CharField(null=True)
    banco = CharField(null=True)
    cta_pago = CharField(null=True)
    afp = CharField(null=True)
    f_ingreso = CharField(null=True)
    f_nac = CharField(null=True)
    ccosto = CharField(null=True)
    sueldo = DecimalField(max_digits=18, decimal_places=2, null=True)
    horas_instruccion = DecimalField(max_digits=18, decimal_places=2, null=True)
    asignacion_familiar = DecimalField(max_digits=18, decimal_places=2, null=True)
    vacaciones = DecimalField(max_digits=18, decimal_places=2, null=True)
    feriado_laborado = DecimalField(max_digits=18, decimal_places=2, null=True)
    horas_extras_25 = DecimalField(max_digits=18, decimal_places=2, null=True)
    movilidad_empresa = DecimalField(max_digits=18, decimal_places=2, null=True)
    adelanto_de_sueldo = DecimalField(max_digits=18, decimal_places=2, null=True)
    descanso_medico = DecimalField(max_digits=18, decimal_places=2, null=True)
    bonificacion_al_cargo = DecimalField(max_digits=18, decimal_places=2, null=True)
    horas_extras_35 = DecimalField(max_digits=18, decimal_places=2, null=True)
    jefe_de_pilotos = DecimalField(max_digits=18, decimal_places=2, null=True)
    instructor_en_vuelo = DecimalField(max_digits=18, decimal_places=2, null=True)
    asignacion_por_festividad = DecimalField(max_digits=18, decimal_places=2, null=True)
    alimentacion = DecimalField(max_digits=18, decimal_places=2, null=True)
    transporte = DecimalField(max_digits=18, decimal_places=2, null=True)
    total_ingresos = DecimalField(max_digits=18, decimal_places=2, null=True)
    afp_aporte = DecimalField(max_digits=18, decimal_places=2, null=True)
    onp = DecimalField(max_digits=18, decimal_places=2, null=True)
    afp_comision = DecimalField(max_digits=18, decimal_places=2, null=True)
    afp_prima_seg = DecimalField(max_digits=18, decimal_places=2, null=True)
    prestamo_al_personal = DecimalField(max_digits=18, decimal_places=2, null=True)
    quinta_categoria = DecimalField(max_digits=18, decimal_places=2, null=True)
    cxc_boletos = DecimalField(max_digits=18, decimal_places=2, null=True)
    retencion_judicial = DecimalField(max_digits=18, decimal_places=2, null=True)
    dscto_x_adel_de_viaticos = DecimalField(max_digits=18, decimal_places=2, null=True)
    libreta_de_vuelo = DecimalField(max_digits=18, decimal_places=2, null=True)
    total_dsctos = DecimalField(max_digits=18, decimal_places=2, null=True)
    neto_a_pagar = DecimalField(max_digits=18, decimal_places=2, null=True)
    essalud = DecimalField(max_digits=18, decimal_places=2, null=True)
    sctr_salud = DecimalField(max_digits=18, decimal_places=2, null=True)
    sctr_pension = DecimalField(max_digits=18, decimal_places=2, null=True)
    vida_ley = DecimalField(max_digits=18, decimal_places=2, null=True)
    total_aportes = DecimalField(max_digits=18, decimal_places=2, null=True)
    eps = DecimalField(max_digits=18, decimal_places=2, null=True)
    retencion = DecimalField(max_digits=18, decimal_places=2, null=True)
    rendicion_de_viaticos = DecimalField(max_digits=18, decimal_places=2, null=True)
    neto = CharField(null=True)
    impneto = DecimalField(max_digits=18, decimal_places=2, null=True)
    regimen = CharField(null=True)
    n_a = CharField(null=True)
    asignacion_al_cargo = DecimalField(max_digits=18, decimal_places=2, null=True)
    bono_de_retencion = DecimalField(max_digits=18, decimal_places=2, null=True)
    proceso_de_entrenamiento_y_habilitacion = DecimalField(
        max_digits=18, decimal_places=2, null=True
    )
    adelanto_de_sueldo_y_otros = DecimalField(max_digits=18, decimal_places=2, null=True)
    adelanto_utilidades = DecimalField(max_digits=18, decimal_places=2, null=True)
    faltante_en_caja_chica = DecimalField(max_digits=18, decimal_places=2, null=True)
    utilidades = DecimalField(max_digits=18, decimal_places=2, null=True)
    bonificacion_por_cierre_de_pliego = DecimalField(
        max_digits=18, decimal_places=2, null=True
    )
    reintegro = DecimalField(max_digits=18, decimal_places=2, null=True)
