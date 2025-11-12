# Barba, Lorena A., and Forsyth, Gilbert F. (2018).
# CFD Python: the 12 steps to Navier-Stokes equations.
# Journal of Open Source Education, 1(9), 21,
# https://doi.org/10.21105/jose.00021
# TODO: License
# (c) 2017 Lorena A. Barba, Gilbert F. Forsyth.
# All content is under Creative Commons Attribution CC-BY 4.0,
# and all code is under BSD-3 clause (previously under MIT, and changed on March 8, 2018).

import datetime

import jax.numpy as jnp
import jax
from jax import lax
from functools import partial


@partial(jax.jit, static_argnums=(0,))
def build_up_b(rho, dt, dx, dy, u, v):
    b = jnp.zeros_like(u)
    b = b.at[1:-1,
      1:-1].set((rho * (1 / dt * ((u[1:-1, 2:] - u[1:-1, 0:-2]) / (2 * dx) +
                                (v[2:, 1:-1] - v[0:-2, 1:-1]) / (2 * dy)) -
                      ((u[1:-1, 2:] - u[1:-1, 0:-2]) / (2 * dx))**2 - 2 *
                      ((u[2:, 1:-1] - u[0:-2, 1:-1]) / (2 * dy) *
                       (v[1:-1, 2:] - v[1:-1, 0:-2]) / (2 * dx)) -
                      ((v[2:, 1:-1] - v[0:-2, 1:-1]) / (2 * dy))**2)))

    # Periodic BC Pressure @ x = 2
    b = b.at[1:-1, -1].set((rho * (1 / dt * ((u[1:-1, 0] - u[1:-1, -2]) / (2 * dx) +
                                    (v[2:, -1] - v[0:-2, -1]) / (2 * dy)) -
                          ((u[1:-1, 0] - u[1:-1, -2]) / (2 * dx))**2 - 2 *
                          ((u[2:, -1] - u[0:-2, -1]) / (2 * dy) *
                           (v[1:-1, 0] - v[1:-1, -2]) / (2 * dx)) -
                          ((v[2:, -1] - v[0:-2, -1]) / (2 * dy))**2)))

    # Periodic BC Pressure @ x = 0
    b = b.at[1:-1, 0].set((rho * (1 / dt * ((u[1:-1, 1] - u[1:-1, -1]) / (2 * dx) +
                                   (v[2:, 0] - v[0:-2, 0]) / (2 * dy)) -
                         ((u[1:-1, 1] - u[1:-1, -1]) / (2 * dx))**2 - 2 *
                         ((u[2:, 0] - u[0:-2, 0]) / (2 * dy) *
                          (v[1:-1, 1] - v[1:-1, -1]) /
                          (2 * dx)) - ((v[2:, 0] - v[0:-2, 0]) / (2 * dy))**2)))

    return b

@partial(jax.jit, static_argnums=(0,))
def pressure_poisson_periodic(nit, p, dx, dy, b):

    def body_func(p, q):
        pn = p.copy()
        p = p.at[1:-1, 1:-1].set(((pn[1:-1, 2:] + pn[1:-1, 0:-2]) * dy**2 +
                          (pn[2:, 1:-1] + pn[0:-2, 1:-1]) * dx**2) /
                         (2 * (dx**2 + dy**2)) - dx**2 * dy**2 /
                         (2 * (dx**2 + dy**2)) * b[1:-1, 1:-1])

        # Periodic BC Pressure @ x = 2
        p = p.at[1:-1, -1].set(((pn[1:-1, 0] + pn[1:-1, -2]) * dy**2 +
                        (pn[2:, -1] + pn[0:-2, -1]) * dx**2) /
                       (2 * (dx**2 + dy**2)) - dx**2 * dy**2 /
                       (2 * (dx**2 + dy**2)) * b[1:-1, -1])

        # Periodic BC Pressure @ x = 0
        p = p.at[1:-1,
          0].set((((pn[1:-1, 1] + pn[1:-1, -1]) * dy**2 +
                 (pn[2:, 0] + pn[0:-2, 0]) * dx**2) / (2 * (dx**2 + dy**2)) -
                dx**2 * dy**2 / (2 * (dx**2 + dy**2)) * b[1:-1, 0]))

        # Wall boundary conditions, pressure
        p = p.at[-1, :].set(p[-2, :])  # dp/dy = 0 at y = 2
        p = p.at[0, :].set(p[1, :])  # dp/dy = 0 at y = 0

        return p, None
    
    p, _ = lax.scan(body_func, p, jnp.arange(nit))


@partial(jax.jit, static_argnums=(0,7,8,9))
def channel_flow(nit, u, v, dt, dx, dy, p, rho, nu, F):
    udiff = 1
    stepcount = 0

    array_vals = (udiff, stepcount, u, v, p)

    def conf_func(array_vals):
        udiff, _, _, _ , _ = array_vals
        return udiff > .001
    
    def body_func(array_vals):
        _, stepcount, u, v, p = array_vals

        un = u.copy()
        vn = v.copy()

        b = build_up_b(rho, dt, dx, dy, u, v)
        pressure_poisson_periodic(nit, p, dx, dy, b)

        u = u.at[1:-1,
          1:-1].set(un[1:-1, 1:-1] - un[1:-1, 1:-1] * dt / dx *
                   (un[1:-1, 1:-1] - un[1:-1, 0:-2]) -
                   vn[1:-1, 1:-1] * dt / dy *
                   (un[1:-1, 1:-1] - un[0:-2, 1:-1]) - dt / (2 * rho * dx) *
                   (p[1:-1, 2:] - p[1:-1, 0:-2]) + nu *
                   (dt / dx**2 *
                    (un[1:-1, 2:] - 2 * un[1:-1, 1:-1] + un[1:-1, 0:-2]) +
                    dt / dy**2 *
                    (un[2:, 1:-1] - 2 * un[1:-1, 1:-1] + un[0:-2, 1:-1])) +
                   F * dt)

        v = v.at[1:-1,
          1:-1].set(vn[1:-1, 1:-1] - un[1:-1, 1:-1] * dt / dx *
                   (vn[1:-1, 1:-1] - vn[1:-1, 0:-2]) -
                   vn[1:-1, 1:-1] * dt / dy *
                   (vn[1:-1, 1:-1] - vn[0:-2, 1:-1]) - dt / (2 * rho * dy) *
                   (p[2:, 1:-1] - p[0:-2, 1:-1]) + nu *
                   (dt / dx**2 *
                    (vn[1:-1, 2:] - 2 * vn[1:-1, 1:-1] + vn[1:-1, 0:-2]) +
                    dt / dy**2 *
                    (vn[2:, 1:-1] - 2 * vn[1:-1, 1:-1] + vn[0:-2, 1:-1])))

        # Periodic BC u @ x = 2
        u = u.at[1:-1, -1].set(
            un[1:-1, -1] - un[1:-1, -1] * dt / dx *
            (un[1:-1, -1] - un[1:-1, -2]) - vn[1:-1, -1] * dt / dy *
            (un[1:-1, -1] - un[0:-2, -1]) - dt / (2 * rho * dx) *
            (p[1:-1, 0] - p[1:-1, -2]) + nu *
            (dt / dx**2 *
             (un[1:-1, 0] - 2 * un[1:-1, -1] + un[1:-1, -2]) + dt / dy**2 *
             (un[2:, -1] - 2 * un[1:-1, -1] + un[0:-2, -1])) + F * dt)

        # Periodic BC u @ x = 0
        u = u.at[1:-1,
          0].set(un[1:-1, 0] - un[1:-1, 0] * dt / dx *
                (un[1:-1, 0] - un[1:-1, -1]) - vn[1:-1, 0] * dt / dy *
                (un[1:-1, 0] - un[0:-2, 0]) - dt / (2 * rho * dx) *
                (p[1:-1, 1] - p[1:-1, -1]) + nu *
                (dt / dx**2 *
                 (un[1:-1, 1] - 2 * un[1:-1, 0] + un[1:-1, -1]) + dt / dy**2 *
                 (un[2:, 0] - 2 * un[1:-1, 0] + un[0:-2, 0])) + F * dt)

        # Periodic BC v @ x = 2
        v = v.at[1:-1, -1].set(
            vn[1:-1, -1] - un[1:-1, -1] * dt / dx *
            (vn[1:-1, -1] - vn[1:-1, -2]) - vn[1:-1, -1] * dt / dy *
            (vn[1:-1, -1] - vn[0:-2, -1]) - dt / (2 * rho * dy) *
            (p[2:, -1] - p[0:-2, -1]) + nu *
            (dt / dx**2 *
             (vn[1:-1, 0] - 2 * vn[1:-1, -1] + vn[1:-1, -2]) + dt / dy**2 *
             (vn[2:, -1] - 2 * vn[1:-1, -1] + vn[0:-2, -1])))

        # Periodic BC v @ x = 0
        v = v.at[1:-1,
          0].set(vn[1:-1, 0] - un[1:-1, 0] * dt / dx *
                (vn[1:-1, 0] - vn[1:-1, -1]) - vn[1:-1, 0] * dt / dy *
                (vn[1:-1, 0] - vn[0:-2, 0]) - dt / (2 * rho * dy) *
                (p[2:, 0] - p[0:-2, 0]) + nu *
                (dt / dx**2 *
                 (vn[1:-1, 1] - 2 * vn[1:-1, 0] + vn[1:-1, -1]) + dt / dy**2 *
                 (vn[2:, 0] - 2 * vn[1:-1, 0] + vn[0:-2, 0])))

        # Wall BC: u,v = 0 @ y = 0,2
        u = u.at[0, :].set(0)
        u = u.at[-1, :].set(0)
        v = v.at[0, :].set(0)
        v = v.at[-1, :].set(0)

        udiff = (jnp.sum(u) - jnp.sum(un)) / jnp.sum(u)
        stepcount += 1

        return (udiff, stepcount, u, v, p)
    
    _, stepcount, _, _, _ = lax.while_loop(conf_func, body_func, array_vals)
    
    return stepcount

def initialize(ny, nx):
    u = jnp.zeros((ny, nx), dtype=jnp.float64)
    v = jnp.zeros((ny, nx), dtype=jnp.float64)
    p = jnp.ones((ny, nx), dtype=jnp.float64)
    dx = 2 / (nx - 1)
    dy = 2 / (ny - 1)
    dt = .1 / ((nx - 1) * (ny - 1))
    return u, v, p, dx, dy, dt

def handler(event):

    if "size" in event:
        size = event["size"]
        ny = size["ny"]
        nx = size["nx"]
        nit = size["nit"]
        rho = size["rho"]
        nu = size["nu"]
        F = size["F"]
    

    generate_begin = datetime.datetime.now()

    u, v, p, dx, dy, dt = initialize(ny, nx)

    generate_end = datetime.datetime.now()
    
    process_begin = datetime.datetime.now()
    
    results = channel_flow(nit, u, v, dt, dx, dy, p, rho, nu, F)

    process_end = datetime.datetime.now()
    
    # y_re_im = jnp.stack([jnp.real(result), jnp.imag(result)], axis=-1).tolist()

    process_time = (process_end - process_begin) / datetime.timedelta(milliseconds=1)
    generate_time = (generate_end - generate_begin) / datetime.timedelta(milliseconds=1)    

    try:
        results = jax.device_get(results)
    except Exception:
        pass

    if hasattr(results, "item"):
        results = results.item()
    elif hasattr(results, "tolist"):
        results = results.tolist()

    return {
            'size': size,
            'result': results,
            'measurement': {
                'compute_time': process_time,
                'generate_time': generate_time
            }
    }
