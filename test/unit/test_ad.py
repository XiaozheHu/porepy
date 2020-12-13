import unittest
import pytest

import numpy as np
import scipy.sparse as sps

from porepy.numerics.ad.forward_mode import Ad_array
import porepy as pp



@pytest.mark.parametrize("scalar", [True])
def test_subdomain_projections(scalar):
    """ Test of subdomain projections. Both face and cell restriction and prolongation.

    Test three specific cases:
        1. Projections generated by passing a bucket and a list of grids are identical
        2. All projections for all grids (individually) in a simple bucket.
        3. Combined projections for list of grids.
    """

    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    gb = pp.meshing.cart_grid(fracs, [2, 2])
    NC = gb.num_cells()
    NF = gb.num_faces()
    Nd = gb.dim_max()

    if not scalar:
        NC *= Nd
        NF *= Nd

    grid_list = np.array([g for g, _ in gb])
    proj = pp.ad.SubdomainProjections(gb=gb)
    proj_list = pp.ad.SubdomainProjections(grids=grid_list)

    cell_start = np.cumsum(np.hstack((0, np.array([g.num_cells for g in grid_list]))))
    face_start = np.cumsum(np.hstack((0, np.array([g.num_faces for g in grid_list]))))

    # Test projection of one fracture at a time for the full set of grids
    for g in grid_list:

        ind = _list_ind_of_grid(grid_list, g)

        nc, nf = g.num_cells, g.num_faces

        row_cell, col_cell, data_cell, row_face, col_face, data_face = _mat_inds(nc, nf, ind, scalar, Nd, cell_start, face_start)

        known_cell_proj = sps.coo_matrix((data_cell, (row_cell, col_cell)),
                                         shape=(g.num_cells, NC)).tocsr()
        known_face_proj = sps.coo_matrix((data_face, (row_face, col_face)),
                                         shape=(g.num_faces, NF)).tocsr()

        assert _compare_matrices(proj.cell_restriction(g),
                                 proj_list.cell_restriction(g))
        assert _compare_matrices(proj.cell_restriction(g), known_cell_proj)
        assert _compare_matrices(proj.cell_prolongation(g), known_cell_proj.T)
        assert _compare_matrices(proj.face_restriction(g),
                                 proj_list.face_restriction(g))
        assert _compare_matrices(proj.face_restriction(g), known_face_proj)
        assert _compare_matrices(proj.face_prolongation(g), known_face_proj.T)

    # Project between the full grid and both 1d grids (to combine two grids)
    g1, g2 = gb.grids_of_dimension(1)
    rc1, cc1, dc1, rf1, cf1, df1 = _mat_inds(g1.num_cells, g1.num_faces,
                                             _list_ind_of_grid(grid_list, g1), scalar, Nd, cell_start, face_start)
    rc2, cc2, dc2, rf2, cf2, df2 = _mat_inds(g2.num_cells, g2.num_faces,
                                             _list_ind_of_grid(grid_list, g2), scalar, Nd, cell_start, face_start)

    # Adjust the indices of the second grid, we will stack the matrices.
    rc2 += rc1.size
    rf2 += rf1.size
    nc = g1.num_cells + g2.num_cells
    nf = g1.num_faces + g2.num_faces

    known_cell_proj = sps.coo_matrix((np.hstack((dc1, dc2)), (np.hstack((rc1, rc2)),
                                                np.hstack((cc1, cc2)))),
                                     shape=(nc, NC)).tocsr()
    known_face_proj = sps.coo_matrix((np.hstack((df1, df2)), (np.hstack((rf1, rf2)),
                                                np.hstack((cf1, cf2)))),
                                     shape=(nf, NF)).tocsr()

    assert _compare_matrices(proj.cell_restriction([g1, g2]), known_cell_proj)
    assert _compare_matrices(proj.cell_prolongation([g1, g2]), known_cell_proj.T)
    assert _compare_matrices(proj.face_restriction([g1, g2]), known_face_proj)
    assert _compare_matrices(proj.face_prolongation([g1, g2]), known_face_proj.T)


@pytest.mark.parametrize("scalar", [True])
def test_mortar_projections(scalar):
    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    gb = pp.meshing.cart_grid(fracs, [2, 2])
    NC = gb.num_cells()
    NF = gb.num_faces()
    Nd = gb.dim_max()

    NMC = gb.num_mortar_cells()

    if not scalar:
        NC *= Nd
        NF *= Nd

    g0 = gb.grids_of_dimension(2)[0]
    g1, g2 = gb.grids_of_dimension(1)
    g3 = gb.grids_of_dimension(0)[0]

    mg01 = gb.edge_props((g0, g1), 'mortar_grid')
    mg02 = gb.edge_props((g0, g2), 'mortar_grid')

    mg13 = gb.edge_props((g1, g3), 'mortar_grid')
    mg23 = gb.edge_props((g2, g3), 'mortar_grid')


    ########
    # First test projection between all grids and all interfaces
    grid_list = np.array([g0, g1, g2, g3])
    edge_list = [(g0, g1), (g0, g2), (g1, g3), (g2, g3)]

    proj = pp.ad.MortarProjections(grids=grid_list, edges=edge_list, gb=gb)

    cell_start = np.cumsum(np.hstack((0, np.array([g.num_cells for g in grid_list]))))
    face_start = np.cumsum(np.hstack((0, np.array([g.num_faces for g in grid_list]))))

    f0 = np.hstack((sps.find(mg01.mortar_to_primary_int())[0],
                     sps.find(mg02.mortar_to_primary_int())[0]))
    f1 = sps.find(mg13.mortar_to_primary_int())[0]
    f2 = sps.find(mg23.mortar_to_primary_int())[0]

    c1 = sps.find(mg01.mortar_to_secondary_int())[0]
    c2 = sps.find(mg02.mortar_to_secondary_int())[0]
    c3 = np.hstack((sps.find(mg13.mortar_to_secondary_int())[0],
                     sps.find(mg23.mortar_to_secondary_int())[0]))

    rows_higher = np.hstack((f0, f1 + face_start[1], f2 + face_start[2]))
    cols_higher = np.arange(NMC)
    data = np.ones(NMC)

    proj_known_higher = sps.coo_matrix((data, (rows_higher, cols_higher)),
                                       shape=(NF, NMC)).tocsr()

    assert _compare_matrices(proj_known_higher, proj.mortar_to_primary_int)
    assert _compare_matrices(proj_known_higher, proj.mortar_to_primary_avg)
    assert _compare_matrices(proj_known_higher.T, proj.primary_to_mortar_int)
    assert _compare_matrices(proj_known_higher.T, proj.primary_to_mortar_avg)

    rows_lower = np.hstack((c1 + cell_start[1], c2 + cell_start[2], c3 + cell_start[3]))
    cols_lower = np.arange(NMC)
    data = np.ones(NMC)

    proj_known_lower = sps.coo_matrix((data, (rows_lower, cols_lower)),
                                       shape=(NC, NMC)).tocsr()
    assert _compare_matrices(proj_known_lower, proj.mortar_to_secondary_int)


@pytest.mark.parametrize("scalar", [True])
def test_divergence_operators(scalar):
    """ Test of divergence operator. Only check equivalence between grid bucket and
    set of list. A test of elements would essentially verify the block-diagonal
    contrucor for sps.spmatrix, which does not seem like worth a test in this setting.

    In practice, this test will mainly check that the construction of a divergence
    operator actually works.
    """
    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    gb = pp.meshing.cart_grid(fracs, [2, 2])

    grid_list = np.array([g for g, _ in gb])
    div = pp.ad.Divergence(gb=gb)
    div_list = pp.ad.Divergence(grids=grid_list)
    assert _compare_matrices(div.parse(gb), div_list.parse(gb))

@pytest.mark.parametrize("scalar", [True])
def test_trace_operators(scalar):
    """ Test of trace operators. Only check equivalence between grid bucket and
    set of list. A test of elements would essentially verify the block-diagonal
    contrucor for sps.spmatrix, which does not seem like worth a test in this setting.

    In practice, this test will mainly check that the construction of a trace
    operator actually works.
    """
    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    gb = pp.meshing.cart_grid(fracs, [2, 2])

    grid_list = np.array([g for g, _ in gb])
    trace = pp.ad.Trace(gb=gb)
    trace_list = pp.ad.Trace(grids=grid_list)
    assert _compare_matrices(trace.trace.parse(gb), trace_list.trace.parse(gb))
    assert _compare_matrices(trace.inv_trace.parse(gb), trace_list.inv_trace.parse(gb))


@pytest.mark.parametrize("scalar", [True, False])
def test_boundary_condition(scalar):
    """ Test of boundary condition representation.
    """
    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    gb = pp.meshing.cart_grid(fracs, [2, 2])

    grid_list = np.array([g for g, _ in gb])

    Nd = gb.dim_max()
    key = 'foo'

    # Start of all faces
    face_start = np.cumsum(np.hstack((0, np.array([g.num_faces for g in grid_list]))))

    # Build values of known values (to be filled during assignment of bcs)
    if scalar:
        known_values = np.zeros(gb.num_faces())
    else:
        known_values = np.zeros(gb.num_faces() * Nd)
        # If vector problem, all faces have Nd numbers
        face_start *= Nd

    # Loop over grids, assign values, keep track of assigned values
    for g, d in gb:
        grid_ind = _list_ind_of_grid(grid_list, g)
        if scalar:
            values = np.random.rand(g.num_faces)
        else:
            values = np.random.rand(g.num_faces * Nd)

        d[pp.PARAMETERS] = {key: {'bc_values': values}}

        # Put face values in the right place in the vector of knowns
        face_inds = np.arange(face_start[grid_ind], face_start[grid_ind+1])
        known_values[face_inds] = values

    # Ad representation of the boundary conditions. Parse.
    bc = pp.ad.BoundaryCondition(key, grid_list)
    val = bc.parse(gb)

    assert np.allclose(val, known_values)


class MockDiscretization:
    def __init__(self, key):
        self.foobar_matrix_key = "foobar"
        self.not_matrix_keys = "failed"

        self.keyword = key


def test_discretization_class():

    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    gb = pp.meshing.cart_grid(fracs, [2, 2])

    grid_list = np.array([g for g, _ in gb])

    # Make two Mock discretizaitons, with different keywords
    key = 'foo'
    sub_key = 'bar'
    discr = MockDiscretization(key)
    sub_discr = MockDiscretization(sub_key)

    # First discretization applies to all grids, the second just to a subset
    discr_map = {g: discr for g in grid_list}
    sub_discr_map = {g: sub_discr for g in grid_list[:2]}

    # Ad wrappers
    discr_ad = pp.ad.Discretization(discr_map)
    sub_discr_ad = pp.ad.Discretization(sub_discr_map)

    # Check that the Ad wrapper has made a field of foobar, but not of the attribute
    # with a slightly misspelled name
    assert hasattr(discr_ad, 'foobar')
    assert not hasattr(discr_ad, 'not')

    # values
    known_val= np.random.rand(len(discr_map))
    known_sub_val= np.random.rand(len(sub_discr_map))

    # Assign a value to the discretization matrix, with the right key
    for vi, g in enumerate(discr_map):
        d = gb.node_props(g)
        d[pp.DISCRETIZATION_MATRICES] = {key: {'foobar': known_val[vi]}}

    # Same with submatrix
    for vi, g in enumerate(sub_discr_map):
        d = gb.node_props(g)
        d[pp.DISCRETIZATION_MATRICES].update({sub_key: {'foobar': known_sub_val[vi]}})

    # Compare values under parsing. Note we need to pick out the diagonal, due to the
    # way parsing make block matrices.
    assert np.allclose(known_val, discr_ad.foobar.parse(gb).diagonal())
    assert np.allclose(known_sub_val, sub_discr_ad.foobar.parse(gb).diagonal())


# Helper method to get indices for sparse matrices
def _mat_inds(nc, nf, grid_ind, scalar, Nd, cell_start, face_start):
    cell_inds = np.arange(cell_start[grid_ind], cell_start[grid_ind+1])
    face_inds = np.arange(face_start[grid_ind], face_start[grid_ind+1])
    if scalar:
        data_cell = np.ones(nc)
        row_cell = np.arange(nc)
        data_face = np.ones(nf)
        row_face = np.arange(nf)
        col_cell = cell_inds
        col_face = face_inds
    else:
        data_cell = np.ones(nc * Nd)
        row_cell = np.arange(nc * Nd)
        data_face = np.ones(nf * Nd)
        row_face = np.arange(nf * Nd)
        col_cell = pp.fvutils.expand_indices_nd(cell_inds, Nd)
        col_face = pp.fvutils.expand_indices_nd(face_inds, Nd)
    return row_cell, col_cell, data_cell, row_face, col_face, data_face



def _compare_matrices(m1, m2):
    if isinstance(m1, pp.ad.Matrix):
        m1 = m1._mat
    if isinstance(m2, pp.ad.Matrix):
        m2 = m2._mat
    if m1.shape != m2.shape:
        return False
    d = m1 - m2
    if d.data.size > 0:
        if np.max(np.abs(d.data)) > 1e-10:
            return False
    return True

def _list_ind_of_grid(grid_list, g):
    for i, gl in enumerate(grid_list):
        if g == gl:
            return i

    raise ValueError("grid is not in list")

class AdArrays(unittest.TestCase):
    def test_add_two_scalars(self):
        a = Ad_array(1, 0)
        b = Ad_array(-10, 0)
        c = a + b
        self.assertTrue(c.val == -9 and c.jac == 0)
        self.assertTrue(a.val == 1 and a.jac == 0)
        self.assertTrue(b.val == -10 and b.jac == 0)

    def test_add_two_ad_variables(self):
        a = Ad_array(4, 1.0)
        b = Ad_array(9, 3)
        c = a + b
        self.assertTrue(np.allclose(c.val, 13) and np.allclose(c.jac, 4.0))
        self.assertTrue(a.val == 4 and np.allclose(a.jac, 1.0))
        self.assertTrue(b.val == 9 and b.jac == 3)

    def test_add_var_with_scal(self):
        a = Ad_array(3, 2)
        b = 3
        c = a + b
        self.assertTrue(np.allclose(c.val, 6) and np.allclose(c.jac, 2))
        self.assertTrue(a.val == 3 and np.allclose(a.jac, 2))
        self.assertTrue(b == 3)

    def test_add_scal_with_var(self):
        a = Ad_array(3, 2)
        b = 3
        c = b + a
        self.assertTrue(np.allclose(c.val, 6) and np.allclose(c.jac, 2))
        self.assertTrue(a.val == 3 and a.jac == 2)
        self.assertTrue(b == 3)

    def test_sub_two_scalars(self):
        a = Ad_array(1, 0)
        b = Ad_array(3, 0)
        c = a - b
        self.assertTrue(c.val == -2 and c.jac == 0)
        self.assertTrue(a.val == 1 and a.jac == 0)
        self.assertTrue(b.val == 3 and a.jac == 0)

    def test_sub_two_ad_variables(self):
        a = Ad_array(4, 1.0)
        b = Ad_array(9, 3)
        c = a - b
        self.assertTrue(np.allclose(c.val, -5) and np.allclose(c.jac, -2))
        self.assertTrue(a.val == 4 and np.allclose(a.jac, 1.0))
        self.assertTrue(b.val == 9 and b.jac == 3)

    def test_sub_var_with_scal(self):
        a = Ad_array(3, 2)
        b = 3
        c = a - b
        self.assertTrue(np.allclose(c.val, 0) and np.allclose(c.jac, 2))
        self.assertTrue(a.val == 3 and a.jac == 2)
        self.assertTrue(b == 3)

    def test_sub_scal_with_var(self):
        a = Ad_array(3, 2)
        b = 3
        c = b - a
        self.assertTrue(np.allclose(c.val, 0) and np.allclose(c.jac, -2))
        self.assertTrue(a.val == 3 and a.jac == 2)
        self.assertTrue(b == 3)

    def test_mul_scal_ad_scal(self):
        a = Ad_array(3, 0)
        b = Ad_array(2, 0)
        c = a * b
        self.assertTrue(c.val == 6 and c.jac == 0)
        self.assertTrue(a.val == 3 and a.jac == 0)
        self.assertTrue(b.val == 2 and b.jac == 0)

    def test_mul_ad_var_ad_scal(self):
        a = Ad_array(3, 3)
        b = Ad_array(2, 0)
        c = a * b
        self.assertTrue(c.val == 6 and c.jac == 6)
        self.assertTrue(a.val == 3 and a.jac == 3)
        self.assertTrue(b.val == 2 and b.jac == 0)

    def test_mul_ad_var_ad_var(self):
        a = Ad_array(3, 3)
        b = Ad_array(2, -4)
        c = a * b
        self.assertTrue(c.val == 6 and c.jac == -6)
        self.assertTrue(a.val == 3 and a.jac == 3)
        self.assertTrue(b.val == 2 and b.jac == -4)

    def test_mul_ad_var_scal(self):
        a = Ad_array(3, 3)
        b = 3
        c = a * b
        self.assertTrue(c.val == 9 and c.jac == 9)
        self.assertTrue(a.val == 3 and a.jac == 3)
        self.assertTrue(b == 3)

    def test_mul_scar_ad_var(self):
        a = Ad_array(3, 3)
        b = 3
        c = b * a
        self.assertTrue(c.val == 9 and c.jac == 9)
        self.assertTrue(a.val == 3 and a.jac == 3)
        self.assertTrue(b == 3)

    def test_mul_ad_var_mat(self):
        x = Ad_array(np.array([1, 2, 3]), sps.diags([3, 2, 1]))
        A = sps.csc_matrix(np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]]))
        f = x * A
        sol = np.array([30, 36, 42])
        jac = np.diag([3, 2, 1]) * A

        self.assertTrue(np.all(f.val == sol) and np.all(f.jac == jac))
        self.assertTrue(
            np.all(x.val == np.array([1, 2, 3])) and np.all(x.jac == np.diag([3, 2, 1]))
        )
        self.assertTrue(np.all(A == np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])))

    def test_advar_mul_vec(self):
        x = Ad_array(np.array([1, 2, 3]), sps.diags([3, 2, 1]))
        A = np.array([1, 3, 10])
        f = x * A
        sol = np.array([1, 6, 30])
        jac = np.diag([3, 6, 10])

        self.assertTrue(np.all(f.val == sol) and np.all(f.jac == jac))
        self.assertTrue(
            np.all(x.val == np.array([1, 2, 3])) and np.all(x.jac == np.diag([3, 2, 1]))
        )

    def test_advar_m_mul_vec_n(self):
        x = Ad_array(np.array([1, 2, 3]), sps.diags([3, 2, 1]))
        vec = np.array([1, 2])
        R = sps.csc_matrix(np.array([[1, 0, 1], [0, 1, 0]]))
        y = R * x
        z = y * vec
        Jy = np.array([[1, 0, 3], [0, 2, 0]])
        Jz = np.array([[1, 0, 3], [0, 4, 0]])
        self.assertTrue(np.all(y.val == [4, 2]))
        self.assertTrue(np.sum(y.full_jac().A - Jy) == 0)
        self.assertTrue(np.all(z.val == [4, 4]))
        self.assertTrue(np.sum(z.full_jac().A - Jz) == 0)

    def test_mul_sps_advar(self):
        J = sps.csc_matrix(np.array([[1, 3, 1], [5, 0, 0], [5, 1, 2]]))
        x = Ad_array(np.array([1, 2, 3]), J)
        A = sps.csc_matrix(np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]]))
        f = A * x

        self.assertTrue(np.all(f.val == [14, 32, 50]))
        self.assertTrue(np.all(f.jac == A * J.A))

    def test_mul_advar_vectors(self):
        Ja = sps.csc_matrix(np.array([[1, 3, 1], [5, 0, 0], [5, 1, 2]]))
        Jb = sps.csc_matrix(np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]]))
        a = Ad_array(np.array([1, 2, 3]), Ja)
        b = Ad_array(np.array([1, 1, 1]), Jb)
        A = sps.csc_matrix(np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]]))

        f = A * a + b
        jac = A * Ja + Jb

        self.assertTrue(np.all(f.val == [15, 33, 51]))
        self.assertTrue(np.sum(f.full_jac() != A * Ja + Jb) == 0)
        self.assertTrue(
            np.sum(Ja != sps.csc_matrix(np.array([[1, 3, 1], [5, 0, 0], [5, 1, 2]])))
            == 0
        )
        self.assertTrue(
            np.sum(Jb != sps.csc_matrix(np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]])))
            == 0
        )

    def test_power_advar_scalar(self):
        a = Ad_array(2, 3)
        b = a ** 2
        self.assertTrue(b.val == 4 and b.jac == 12)

    def test_power_advar_advar(self):
        a = Ad_array(4, 4)
        b = Ad_array(-8, -12)
        c = a ** b
        jac = -(2 + 3 * np.log(4)) / 16384
        self.assertTrue(np.allclose(c.val, 4 ** -8) and np.allclose(c.jac, jac))

    def test_rpower_advar_scalar(self):
        a = Ad_array(2, 3)
        b = 2 ** a
        self.assertTrue(b.val == 4 and b.jac == 12 * np.log(2))

    def test_rpower_advar_vector_scalar(self):
        J = sps.csc_matrix(np.array([[1, 2], [2, 3], [0, 1]]))
        a = Ad_array(np.array([1, 2, 3]), J)
        b = 3 ** a
        bJac = np.array(
            [
                [3 * np.log(3) * 1, 3 * np.log(3) * 2],
                [9 * np.log(3) * 2, 9 * np.log(3) * 3],
                [27 * np.log(3) * 0, 27 * np.log(3) * 1],
            ]
        )

        self.assertTrue(np.all(b.val == [3, 9, 27]))
        self.assertTrue(np.all(b.jac.A == bJac))

    def test_div_advar_scalar(self):
        a = Ad_array(10, 6)
        b = 2
        c = a / b
        self.assertTrue(c.val == 5, c.jac == 2)

    def test_div_advar_advar(self):
        # a = x ^ 3: b = x^2: x = 2
        a = Ad_array(8, 12)
        b = Ad_array(4, 4)
        c = a / b
        self.assertTrue(c.val == 2 and np.allclose(c.jac, 1))

    def test_full_jac(self):
        J1 = sps.csc_matrix(
            np.array([[1, 3, 5], [1, 5, 1], [6, 2, 4], [2, 4, 1], [6, 2, 1]])
        )
        J2 = sps.csc_matrix(np.array([[1, 2], [2, 5], [6, 0], [9, 9], [45, 2]]))
        J = np.array(
            [
                [1, 3, 5, 1, 2],
                [1, 5, 1, 2, 5],
                [6, 2, 4, 6, 0],
                [2, 4, 1, 9, 9],
                [6, 2, 1, 45, 2],
            ]
        )

        a = Ad_array(np.array([1, 2, 3, 4, 5]), J.copy())  # np.array([J1, J2]))

        self.assertTrue(np.sum(a.full_jac() != J) == 0)

    def test_copy_scalar(self):
        a = Ad_array(1, 0)
        b = a.copy()
        self.assertTrue(a.val == b.val)
        self.assertTrue(a.jac == b.jac)
        a.val = 2
        a.jac = 3
        self.assertTrue(b.val == 1)
        self.assertTrue(b.jac == 0)

    def test_copy_vector(self):
        a = Ad_array(np.ones((3, 1)), np.ones((3, 1)))
        b = a.copy()
        self.assertTrue(np.allclose(a.val, b.val))
        self.assertTrue(np.allclose(a.jac, b.jac))
        a.val[0] = 3
        a.jac[2] = 4
        self.assertTrue(np.allclose(b.val, np.ones((3, 1))))
        self.assertTrue(np.allclose(b.jac, np.ones((3, 1))))


if __name__ == "__main__":
    test_subdomain_projections()
    unittest.main()
