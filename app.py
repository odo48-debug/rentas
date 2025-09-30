from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import date

app = FastAPI(title="Capitalización de Rentas - Simplificado")

VIDA_ECONOMICA = {
    "vivienda": 100,
    "oficina": 75,
    "local_comercial": 50,
    "industrial": 35
}

class RentInput(BaseModel):
    # --- Comunes ---
    fecha_valoracion: date
    superficie_m2: float
    porcentaje_gastos: float     # unidades (ej: 5 = 5%)
    valor_suelo: float           # ahora se pasa directamente
    plusvalia_anual: float       # unidades (ej: 2 = 2%)
    tasa_actualizacion: float    # unidades (ej: 10 = 10%)
    ipc_anual: Optional[float] = 0.0   # unidades (ej: 2 = 2%)

    # --- Con contrato ---
    fecha_inicio_contrato: Optional[date] = None
    vigencia_anios: Optional[int] = None
    renta_mensual: Optional[float] = None

    # --- Sin contrato ---
    fecha_construccion: Optional[date] = None
    tipologia: Optional[str] = None
    renta_m2_mes: Optional[float] = None


class RentOutput(BaseModel):
    valor_actual: float
    valor_reversion: float
    flujos_actualizados: Dict[str, float]
    parametros: dict
    n_periodos: float


@app.post("/capitalizacion_rentas", response_model=RentOutput)
def calcular_capitalizacion(data: RentInput):

    # --- Conversión de porcentajes ---
    porcentaje_gastos = data.porcentaje_gastos / 100
    plusvalia_anual = data.plusvalia_anual / 100
    tasa_actualizacion = data.tasa_actualizacion / 100
    ipc_anual = data.ipc_anual / 100

    # --- Detectar modo ---
    if data.renta_mensual:  
        # Con contrato
        fecha_fin_contrato = date(
            data.fecha_inicio_contrato.year + data.vigencia_anios,
            data.fecha_inicio_contrato.month,
            data.fecha_inicio_contrato.day
        )
        dias_restantes = (fecha_fin_contrato - data.fecha_valoracion).days
        n_periodos = dias_restantes / 365.0
        renta_bruta_anual = data.renta_mensual * 12

    elif data.renta_m2_mes:
        # Sin contrato (mercado/testigos)
        antiguedad = (data.fecha_valoracion.year - data.fecha_construccion.year) - (
            (data.fecha_valoracion.month, data.fecha_valoracion.day) <
            (data.fecha_construccion.month, data.fecha_construccion.day)
        )
        vida_economica = VIDA_ECONOMICA.get(data.tipologia.lower())
        if not vida_economica:
            return RentOutput(
                valor_actual=0,
                valor_reversion=0,
                flujos_actualizados={},
                parametros={"error": f"Tipología no reconocida: {data.tipologia}"},
                n_periodos=0
            )
        n_periodos = vida_economica - antiguedad
        renta_bruta_anual = data.renta_m2_mes * data.superficie_m2 * 12

    else:
        return RentOutput(
            valor_actual=0,
            valor_reversion=0,
            flujos_actualizados={},
            parametros={"error": "Debes pasar renta_mensual (contrato) o renta_m2_mes (mercado)"},
            n_periodos=0
        )

    if n_periodos <= 0:
        return RentOutput(
            valor_actual=0,
            valor_reversion=0,
            flujos_actualizados={},
            parametros={"error": "El horizonte de explotación es 0 o negativo"},
            n_periodos=0
        )

    # --- Gastos y flujo neto ---
    gastos_anuales = renta_bruta_anual * porcentaje_gastos
    flujo_neto_base = renta_bruta_anual - gastos_anuales

    # --- Valor de reversión ---
    valor_reversion = data.valor_suelo * ((1 + plusvalia_anual) ** n_periodos)

    # --- Flujos actualizados ---
    flujos_actualizados: Dict[str, float] = {}
    valor_actualizado = 0.0
    años_enteros = int(n_periodos)
    fraccion = n_periodos - años_enteros

    for t in range(1, años_enteros + 1):
        flujo_neto = flujo_neto_base * ((1 + ipc_anual) ** (t - 1))
        tiempo = (t - 0.5)
        valor_flujo = flujo_neto / ((1 + tasa_actualizacion) ** tiempo)
        flujos_actualizados[str(t)] = round(valor_flujo, 2)
        valor_actualizado += valor_flujo

    if fraccion > 0:
        flujo_neto_parcial = flujo_neto_base * ((1 + ipc_anual) ** años_enteros) * fraccion
        tiempo = años_enteros + fraccion / 2
        valor_flujo = flujo_neto_parcial / ((1 + tasa_actualizacion) ** tiempo)
        flujos_actualizados[f"{años_enteros + fraccion:.2f}"] = round(valor_flujo, 2)
        valor_actualizado += valor_flujo

    valor_reversion_actualizado = valor_reversion / ((1 + tasa_actualizacion) ** n_periodos)
    valor_actualizado += valor_reversion_actualizado

    return RentOutput(
        valor_actual=round(valor_actualizado, 2),
        valor_reversion=round(valor_reversion_actualizado, 2),
        flujos_actualizados=flujos_actualizados,
        parametros={
            "renta_bruta_anual": renta_bruta_anual,
            "gastos_anuales": gastos_anuales,
            "flujo_neto_base": flujo_neto_base,
            "valor_suelo": data.valor_suelo
        },
        n_periodos=round(n_periodos, 2)
    )
