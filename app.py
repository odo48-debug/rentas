from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import date

app = FastAPI(title="Capitalización de Rentas - Unificado")

VIDA_ECONOMICA = {
    "vivienda": 100,
    "oficina": 75,
    "local_comercial": 50,
    "industrial": 35
}

class RentInput(BaseModel):
    # --- Campos comunes ---
    fecha_valoracion: date
    superficie_m2: float
    porcentaje_gastos: float
    valor_mercado_m2: float
    coste_construccion_m2: float
    otros_gastos_m2: float
    coef_b: float
    plusvalia_anual: float
    tasa_actualizacion: float
    ipc_anual: Optional[float] = 0.0

    # --- Opción 1: Con contrato ---
    fecha_inicio_contrato: Optional[date] = None
    vigencia_anios: Optional[int] = None
    renta_mensual: Optional[float] = None

    # --- Opción 2: Sin contrato ---
    fecha_construccion: Optional[date] = None
    tipologia: Optional[str] = None
    renta_m2_mes: Optional[float] = None


class RentOutput(BaseModel):
    valor_actual: float
    valor_reversion: float
    flujos_actualizados: Dict[str, float]
    parametros: dict
    n_periodos: float
    modo: str   # "contrato" o "mercado"


@app.post("/capitalizacion_rentas", response_model=RentOutput)
def calcular_capitalizacion(data: RentInput):

    # --- Detectar modo ---
    if data.renta_mensual:  
        modo = "contrato"
        # Fecha fin contrato
        fecha_fin_contrato = date(
            data.fecha_inicio_contrato.year + data.vigencia_anios,
            data.fecha_inicio_contrato.month,
            data.fecha_inicio_contrato.day
        )
        dias_restantes = (fecha_fin_contrato - data.fecha_valoracion).days
        n_periodos = dias_restantes / 365.0
        renta_bruta_anual = data.renta_mensual * 12

    elif data.renta_m2_mes:
        modo = "mercado"
        # Antigüedad
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
                n_periodos=0,
                modo="mercado"
            )
        n_periodos = vida_economica - antiguedad
        renta_bruta_anual = data.renta_m2_mes * data.superficie_m2 * 12

    else:
        return RentOutput(
            valor_actual=0,
            valor_reversion=0,
            flujos_actualizados={},
            parametros={"error": "Debes pasar renta_mensual (contrato) o renta_m2_mes (mercado)"},
            n_periodos=0,
            modo="error"
        )

    if n_periodos <= 0:
        return RentOutput(
            valor_actual=0,
            valor_reversion=0,
            flujos_actualizados={},
            parametros={"error": "El horizonte de explotación es 0 o negativo"},
            n_periodos=0,
            modo=modo
        )

    # --- Gastos anuales ---
    gastos_anuales = renta_bruta_anual * data.porcentaje_gastos
    flujo_neto_base = renta_bruta_anual - gastos_anuales

    # --- Valor del suelo ---
    vm_total = data.valor_mercado_m2 * data.superficie_m2
    coste_construccion_total = data.coste_construccion_m2 * data.superficie_m2
    otros_gastos_total = data.otros_gastos_m2 * data.superficie_m2
    valor_suelo = vm_total * (1 - data.coef_b) - (coste_construccion_total + otros_gastos_total)

    # --- Valor de reversión ---
    valor_reversion = valor_suelo * ((1 + data.plusvalia_anual) ** n_periodos)

    # --- Actualización de flujos ---
    flujos_actualizados: Dict[str, float] = {}
    valor_actualizado = 0.0
    años_enteros = int(n_periodos)
    fraccion = n_periodos - años_enteros

    for t in range(1, años_enteros + 1):
        flujo_neto = flujo_neto_base * ((1 + data.ipc_anual) ** (t - 1))
        tiempo = (t - 0.5)
        valor_flujo = flujo_neto / ((1 + data.tasa_actualizacion) ** tiempo)
        flujos_actualizados[str(t)] = round(valor_flujo, 2)
        valor_actualizado += valor_flujo

    if fraccion > 0:
        flujo_neto_parcial = flujo_neto_base * ((1 + data.ipc_anual) ** años_enteros) * fraccion
        tiempo = años_enteros + fraccion / 2
        valor_flujo = flujo_neto_parcial / ((1 + data.tasa_actualizacion) ** tiempo)
        flujos_actualizados[f"{años_enteros + fraccion:.2f}"] = round(valor_flujo, 2)
        valor_actualizado += valor_flujo

    valor_reversion_actualizado = valor_reversion / ((1 + data.tasa_actualizacion) ** n_periodos)
    valor_actualizado += valor_reversion_actualizado

    return RentOutput(
        valor_actual=round(valor_actualizado, 2),
        valor_reversion=round(valor_reversion_actualizado, 2),
        flujos_actualizados=flujos_actualizados,
        parametros={
            "renta_bruta_anual": renta_bruta_anual,
            "gastos_anuales": gastos_anuales,
            "flujo_neto_base": flujo_neto_base,
            "valor_suelo": valor_suelo
        },
        n_periodos=round(n_periodos, 2),
        modo=modo
    )
