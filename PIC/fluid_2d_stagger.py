import taichi as ti
import numpy as np
import time



ti.init(arch=ti.gpu)


res = 512
dt = 0.01

# 1, 2, 3
# RK = 3

#
# enable_BFECC = True

#
# enable_clipping = True


rho = 1000
jacobi_iters = 300


length = 6.0

m_g = 32
m_p = m_g
n_grid = m_g*m_g
n_particle = m_p*m_p

dx = length/m_g
inv_dx = 1/dx


eps = 1e-5

debug = False



# colors = ti.Vector(3, dt=ti.f32, shape=(m_g, m_g))
# new_colors = ti.Vector(3, dt=ti.f32, shape=(n, n))
# new_new_colors = ti.Vector(3, dt=ti.f32, shape=(n, n))

velocities_u = ti.var(dt=ti.f32, shape=(m_g+1, m_g))
velocities_v = ti.var(dt=ti.f32, shape=(m_g, m_g+1))
# new_velocities = ti.Vector(2, dt=ti.f32, shape=(m_g, m_g))
# new_new_velocities = ti.Vector(2, dt=ti.f32, shape=(n, n))

pressures = ti.var(dt=ti.f32, shape=(m_g, m_g))
new_pressures = ti.var(dt=ti.f32, shape=(m_g, m_g))

divergences = ti.var(dt=ti.f32, shape=(m_g, m_g))



# weights = ti.var(dt=ti.f32, shape=(m_g, m_g))
weights_u = ti.var(dt=ti.f32, shape=(m_g+1, m_g))
weights_v = ti.var(dt=ti.f32, shape=(m_g, m_g+1))

# 0: fluid
# 1: air
# 2: solid
FLUID = 0
AIR = 1
SOLID = 2
types = ti.var(dt=ti.i32, shape=(m_g, m_g))

particle_velocity = ti.Vector(2, dt=ti.f32, shape=n_particle)
particle_position = ti.Vector(2, dt=ti.f32, shape=n_particle)




# screen center. The simualation area is (0, 0) to (1, 1)
center = ti.Vector([0.5, 0.5])

# cell center
stagger = ti.Vector([0.5, 0.5])


@ti.kernel
def init_grid():
	for i, j in types:
		if i <= 1 or i >= m_g-2 or j <= 1 or j >= m_g-2:
			types[i, j] = SOLID


@ti.kernel
def init_particle():
	for i in particle_position:
		# particle_position[i] = ti.Vector([i%m_p / m_p / 1.5, i//m_p / m_p / 1.5]) + ti.Vector([0.1, 0.25])
		particle_position[i] = ti.Vector([ti.random(), ti.random()]) * 0.6 * 5  + ti.Vector([0.55, 0.65])
		particle_velocity[i] = ti.Vector([0.0, 0.0])


# @ti.kernel
# def advect_particle():
# 	for i in particle_velocity:
# 		particle_velocity[i] = particle_velocity[i] + ti.Vector([0, -9.8]) * dt * 0.01 

# 	# print(particle_position[0])


@ti.func
def is_valid(i, j):
	return i >= 0 and i <= m_g-1 and j >= 0 and j <= m_g-1

@ti.func
def is_solid(i, j):
	return is_valid(i, j) and types[i, j] == SOLID

@ti.func
def is_air(i, j):
	return is_valid(i, j) and types[i, j] == AIR

@ti.func
def is_fluid(i, j):
	return is_valid(i, j) and types[i, j] == FLUID


@ti.func
def handle_boundary():

	for i, j in velocities_u:
		if is_solid(i-1, j) or is_solid(i, j):
			velocities_u[i, j] = 0.0	
	
	for i, j in velocities_v:
		if is_solid(i, j-1) or is_solid(i, j):
			velocities_v[i, j] = 0.0



@ti.func
def scatter(grid_v, grid_m, xp, vp, stagger):
    base = (xp * inv_dx - (stagger + 0.5)).cast(ti.i32)
    fx = xp * inv_dx - (base.cast(ti.f32) + stagger)

    w = [0.5*(1.5-fx)**2, 0.75-(fx-1)**2, 0.5*(fx-0.5)**2] # Bspline

    for i in ti.static(range(3)):
        for j in ti.static(range(3)):
            offset = ti.Vector([i, j])
            weight = w[i][0] * w[j][1]
            grid_v[base + offset] += weight * vp
            grid_m[base + offset] += weight


@ti.kernel
def particle_to_grid():

	


	# for i, j in velocities_u:
	# 	velocities_u[i, j] = 0.0
	# 	weights_u[i, j] = 0.0

	# for i, j in velocities_v:
	# 	velocities_v[i, j] = 0.0
	# 	weights_v[i, j] = 0.0
		# if not is_solid(i, j-1) and not is_solid(i, j):
		# 	velocities_v[i, j] += -9.8 * dt

	for i, j in types:
		if not is_solid(i, j):
			types[i, j] = AIR
			# divergences[i, j] = 0.0
			pressures[i, j] = 0.0
			new_pressures[i, j] = 0.0

	for k in particle_velocity:

		grid = (particle_position[k] * inv_dx).cast(int)
		types[grid] = FLUID

		stagger_u = ti.Vector([0.0, 0.5])
		stagger_v = ti.Vector([0.5, 0.0])
		scatter(velocities_u, weights_u, particle_position[k], particle_velocity[k].x, stagger_u)
		scatter(velocities_v, weights_v, particle_position[k], particle_velocity[k].y, stagger_v)

	for k in ti.grouped(weights_u):
		weight = weights_u[k]
		if weight > 0:
			velocities_u[k] = velocities_u[k] / weight

	for k in ti.grouped(weights_v):
		weight = weights_v[k]
		if weight > 0:
			velocities_v[k] = velocities_v[k] / weight

	for i, j in velocities_v:
		# if not is_solid(i, j-1) and not is_solid(i, j):
			velocities_v[i, j] += -9.8 * dt

	handle_boundary()



@ti.kernel
def solve_divergence():

	for i, j in divergences:
		if not is_solid(i, j):

			# v_c = velocities[i, j]
			v_l = velocities_u[i, j]
			v_r = velocities_u[i+1, j]
			v_d = velocities_v[i, j]
			v_u = velocities_v[i, j+1]


			div = v_r - v_l + v_u - v_d

			if is_solid(i-1, j): 
				div += v_l
			if is_solid(i+1, j): 
				div -= v_r
			if is_solid(i, j-1): 
				div += v_d
			if is_solid(i, j+1): 
				div -= v_u

			# if types[i, j] == AIR:
			# 	div = 0.0

			divergences[i, j] = div / (dx)


@ti.kernel
def pressure_jacobi(pressures:ti.template(), new_pressures:ti.template()):

	for i, j in pressures:
		if not is_solid(i, j):


			v_l = velocities_u[i, j]
			v_r = velocities_u[i+1, j]
			v_d = velocities_v[i, j]
			v_u = velocities_v[i, j+1]

			div = v_r - v_l + v_u - v_d


			if is_solid(i-1, j): 
				div += v_l
			if is_solid(i+1, j): 
				div -= v_r
			if is_solid(i, j-1): 
				div += v_d
			if is_solid(i, j+1): 
				div -= v_u
			div /= dx

			p_l = pressures[i-1, j]
			p_r = pressures[i+1, j]
			p_d = pressures[i, j-1]
			p_u = pressures[i, j+1]

			k = 4
			if is_solid(i-1, j):
				p_l = 0.0
				k -= 1
			if is_solid(i+1, j):
				p_r = 0.0
				k -= 1
			if is_solid(i+1, j):
				p_d = 0.0
				k -= 1
			if is_solid(i, j+1):
				p_u = 0.0
				k -= 1

			if is_air(i-1, j):
				p_l = 0.0
			if is_air(i+1, j):
				p_r = 0.0
			if is_air(i, j-1):
				p_d = 0.0
			if is_air(i, j+1):
				p_u = 0.0

			# new_pressures[i, j] = 1/3 * pressures[i, j] + 2/3 *  ( p_l + p_r + p_d + p_u - divergences[i, j] * rho / dt * (dx*dx/4) ) / k
			# new_pressures[i, j] =  ( p_l + p_r + p_d + p_u - divergences[i, j] * rho / dt * (dx*dx) ) / k
			new_pressures[i, j] =  ( p_l + p_r + p_d + p_u - div * rho / dt * (dx*dx) ) / k



@ti.kernel
def projection():
	for i, j in ti.ndrange(m_g, m_g):
		if is_fluid(i-1, j) or is_fluid(i, j):
			if is_solid(i-1, j) or is_solid(i, j):
				velocities_u[i, j] = 0.0
			else:
				velocities_u[i, j] -= (pressures[i, j] - pressures[i-1, j]) / dx / rho * dt
				# t = pressures[i, j] - pressures[i-1, j]
				# if t > eps:
				# 	print(t)
				# print(pressures[i]-pre)

		if is_fluid(i, j-1) or is_fluid(i, j):
			if is_solid(i, j-1) or is_solid(i, j):
				velocities_v[i, j] = 0.0
			else:
				velocities_v[i, j] -= (pressures[i, j] - pressures[i, j-1]) / dx / rho * dt


	# for k in ti.grouped(velocities_u):
	# 	if velocities_u[k] > eps:
	# 		print(velocities_u[k])

	# for k in ti.grouped(divergences):
	# 	if is_air(k.x, k.y) and divergences[k] > eps and divergences[k] > 200:
	# 		print("div ", k, divergences[k])
	# 		types[k] = SOLID
	# print("----")

	# for k in ti.grouped(pressures):
	# 	if is_air(k.x, k.y) and pressures[k] > eps:
	# 		print(pressures[k])
	# for i, j in velocities_v:
	# 	if is_solid(i, j-1) or is_solid(i, j):
	# 		velocities_v[i, j] = 0.0
	# 	else:
	# 		p_l = pressures[i-1, j]
	# 		p_r = pressures[i, j]
	# 		p_d = pressures[i, j-1]
	# 		p_u = pressures[i, j]
	# 		grad_p = ti.Vector([p_r - p_l, p_u - p_d]) / (dx)
	# 		velocities_v[i, j] -= grad_p.y / rho * dt



    # scale = dt / (rho * dx)
    # for i, j in ti.ndrange(m, n):
    #     if is_fluid(i - 1, j) or is_fluid(i, j):
    #         if is_solid(i - 1, j) or is_solid(i, j):
    #             u[i, j] = 0
    #         else:
    #             u[i, j] -= scale * (p[i, j] - p[i - 1, j])

    #     if is_fluid(i, j - 1) or is_fluid(i, j):
    #         if is_solid(i, j - 1) or is_solid(i, j):
    #             v[i, j] = 0
    #         else:
    #             v[i, j] -= scale * (p[i, j] - p[i, j - 1])


@ti.func
def gather(grid_v, xp, stagger):
    base = (xp * inv_dx - (stagger + 0.5)).cast(ti.i32)
    fx = xp * inv_dx - (base.cast(ti.f32) + stagger)

    w = [0.5*(1.5-fx)**2, 0.75-(fx-1)**2, 0.5*(fx-0.5)**2] # Bspline

    v_pic = 0.0

    for i in ti.static(range(3)):
        for j in ti.static(range(3)):
            offset = ti.Vector([i, j])
            weight = w[i][0] * w[j][1]
            v_pic += weight * grid_v[base + offset]

    # if v_pic > 1e5:
    # 	print(v_pic)
    return v_pic




@ti.kernel
def grid_to_particle():


	for k in particle_velocity:
		stagger_u = ti.Vector([0.0, 0.5])
		stagger_v = ti.Vector([0.5, 0.0])
		new_u = gather(velocities_u, particle_position[k], stagger_u)
		new_v = gather(velocities_v, particle_position[k], stagger_v)


		vel = ti.Vector([new_u, new_v])

		new_p = particle_position[k] + vel * dt

		# if new_u > eps:
			# print(new_u)



		if new_p.x < dx*2:
			new_p.x = dx*2
			new_u = 0
		if new_p.x >= length - dx*2:
			new_p.x = length - dx*2 - eps
			new_u = 0
			
		if new_p.y < dx*2:
			new_p.y = dx*2
			new_v = 0
		if new_p.y >= length - dx*2:
			new_p.y = length - dx*2 - eps
			new_v = 0


		particle_position[k] = new_p

		particle_velocity[k] = vel




def step():
	# advect_particle()


	velocities_u.fill(0.0)
	velocities_v.fill(0.0)
	weights_u.fill(0.0)
	weights_v.fill(0.0)
	divergences.fill(0.0)

	particle_to_grid()

	solve_divergence()
	
	for i in range(jacobi_iters):
		global pressures, new_pressures
		pressure_jacobi(pressures, new_pressures)
		pressures, new_pressures = new_pressures, pressures


	projection()

	grid_to_particle()





@ti.kernel
def test():
	print(particle_velocity[0])


# init_velocity_field()


init_grid()
init_particle()




gui = ti.GUI("Fluid 2D", (res, res))


# result_dir = "./fluid_2d"
# video_manager = ti.VideoManager(output_dir=result_dir, framerate=30, automatic_build=False)

# pre_mouse_pos = None
# cur_mouse_pos = None
first = True

for frame in range(450000):

	if first:
		# first = False
		for i in range(4):
			step()
	# break

	# if frame <= 42:
		# test()

	# time.sleep(0.2)

	# break
	if debug:
		for i in range(m_g):
			for j in range(m_g):
				color = 0
				if types[i, j] == FLUID:
					color = 0xFFFFFF
				elif types[i, j] == AIR:
					color = 0x0000FF
				elif types[i, j] == SOLID:
					color = 0xFF0000
				gui.circle([(i+0.5)/m_g, (j+0.5)/m_g], radius = 2, color = color)
				# gui.line([i*dx, j*dx], [i*dx, (j+1)*dx], color = 0xFF0000)
				# gui.line([i*dx, (j+1)*dx], [(i+1)*dx, (j+1)*dx], color = 0xFF0000)
				# gui.line([(i+1)*dx, j*dx], [(i+1)*dx, (j+1)*dx], color = 0xFF0000)
				# gui.line([(i+1)*dx, j*dx], [i*dx, j*dx], color = 0xFF0000)

	gui.circles(particle_position.to_numpy() / length, radius=1, color=0xFFFFFF)


	
	gui.show()
	# break

	# video_manager.write_frame(colors.to_numpy())

# video_manager.make_video(gif=True, mp4=True)