import tensorflow as tf
from GPflow.tf_wraps import eye
from GPflow import settings
from functools import reduce
float_type = settings.dtypes.float_type
import numpy as np


class BlockDiagMat_many:
    def __init__(self, mats):
        self.mats = mats
        self.shape = (sum([m.shape[0] for m in mats]), sum([m.shape[1] for m in mats]))
        self.sqrt_dims = sum([m.sqrt_dims for m in mats])

    def _get_rhs_slices(self, X):
        ret = []
        start = 0
        for m in self.mats:
            ret.append(tf.slice(X, begin=tf.pack([start, 0]), size=tf.pack([m.shape[1], -1])))
            start = start + m.shape[1]
        return ret

    def _get_rhs_blocks(self, X):
        """
        X is a solid matrix, same size as this one. Get the blocks of X that
        correspond to the structure of this matrix
        """
        ret = []
        start1 = 0
        start2 = 0
        for m in self.mats:
            ret.append(tf.slice(X, begin=tf.pack([start1, start2]), size=m.shape))
            start1 = start1 + m.shape[0]
            start2 = start2 + m.shape[1]
        return ret

    def get(self):
        ret = self.mats[0].get()
        for m in self.mats[1:]:
            tr_shape = tf.pack([tf.shape(ret)[0], m.shape[1]])
            bl_shape = tf.pack([m.shape[0], tf.shape(ret)[1]])
            top = tf.concat(1, [ret, tf.zeros(tr_shape, float_type)])
            bottom = tf.concat(1, [tf.zeros(bl_shape, float_type), m.get()])
            ret = tf.concat(0, [top, bottom])
        return ret

    def logdet(self):
        return reduce(tf.add, [m.logdet() for m in self.mats])

    def matmul(self, X):
        return tf.concat(0, [m.matmul(Xi) for m, Xi in zip(self.mats, self._get_rhs_slices(X))])

    def solve(self, X):
        return tf.concat(0, [m.solve(Xi) for m, Xi in zip(self.mats, self._get_rhs_slices(X))])

    def trace_KiX(self, X):
        """
        X is a square matrix of the same size as this one.
        if self is K, compute tr(K^{-1} X)
        """
        return reduce(tf.add, [m.trace_KiX(Xi) for m, Xi in zip(self.mats, self._get_rhs_blocks(X))])

    def get_diag(self):
        return tf.concat(0, [m.get_diag() for m in self.mats])

    def inv_diag(self):
        return tf.concat(0, [m.inv_diag() for m in self.mats])

    def matmul_sqrt(self, X):
        return tf.concat(0, [m.matmul_sqrt(Xi) for m, Xi in zip(self.mats, self._get_rhs_slices(X))])

    def matmul_sqrt_transpose(self, X):
        ret = []
        start = np.zeros((2, np.int32))
        for m in self.mats:
            ret.append(m.matmul_sqrt_transpose(tf.slice(X, begin=start, size=tf.pack([m.sqrt_dims, -1]))))
            start[0] += m.sqrt_dims

        return tf.concat(0, ret)


class BlockDiagMat:
    def __init__(self, A, B):
        self.A, self.B = A, B
        self.shape = (A.shape[0] + B.shape[0], A.shape[1] + B.shape[1])
        self.sqrt_dims = A.sqrt_dims + B.sqrt_dims
        self.shape0, self.shape1 = self.shape

    def _get_rhs_slices(self, X):
        # X1 = X[:self.A.shape[1], :]
        X1 = tf.slice(X, begin=tf.zeros((2,), tf.int32), size=tf.pack([self.A.shape[1], -1]))
        # X2 = X[self.A.shape[1]:, :]
        X2 = tf.slice(X, begin=tf.pack([self.A.shape[1], 0]), size=-tf.ones((2,), tf.int32))
        return X1, X2

    def get(self):
        tl_shape = tf.pack([self.A.shape[0], self.B.shape[1]])
        br_shape = tf.pack([self.B.shape[0], self.A.shape[1]])
        top = tf.concat(1, [self.A.get(), tf.zeros(tl_shape, float_type)])
        bottom = tf.concat(1, [tf.zeros(br_shape, float_type), self.B.get()])
        return tf.concat(0, [top, bottom])

    def logdet(self):
        return self.A.logdet() + self.B.logdet()

    def matmul(self, X):
        X1, X2 = self._get_rhs_slices(X)
        top = self.A.matmul(X1)
        bottom = self.B.matmul(X2)
        return tf.concat(0, [top, bottom])

    def solve(self, X):
        X1, X2 = self._get_rhs_slices(X)
        top = self.A.solve(X1)
        bottom = self.B.solve(X2)
        return tf.concat(0, [top, bottom])

    def trace_KiX(self, X):
        """
        X is a square matrix of the same size as this one.
        if self is K, compute tr(K^{-1} X)
        """
        X1, X2 = tf.slice(X, [0, 0], self.A.shape), tf.slice(X, self.A.shape, [-1, -1])
        top = self.A.trace_KiX(X1)
        bottom = self.B.trace_KiX(X2)
        return top + bottom

    def get_diag(self):
        return tf.concat(0, [self.A.get_diag(), self.B.get_diag()])

    def inv_diag(self):
        return tf.concat(0, [self.A.inv_diag(), self.B.inv_diag()])

    def matmul_sqrt(self, X):
        X1, X2 = self._get_rhs_slices(X)
        top = self.A.matmul_sqrt(X1)
        bottom = self.B.matmul_sqrt(X2)
        return tf.concat(0, [top, bottom])

    def matmul_sqrt_transpose(self, X):
        X1 = tf.slice(X, begin=tf.zeros((2,), tf.int32), size=tf.pack([self.A.sqrt_dims, -1]))
        X2 = tf.slice(X, begin=tf.pack([self.A.sqrt_dims, 0]), size=-tf.ones((2,), tf.int32))
        top = self.A.matmul_sqrt_transpose(X1)
        bottom = self.B.matmul_sqrt_transpose(X2)

        return tf.concat(0, [top, bottom])


class LowRankMat:
    def __init__(self, d, W):
        """
        A matrix of the form

            diag(d) + W W^T

        """
        self.d = d
        self.W = W
        self.shape = (tf.size(self.d), tf.size(self.d))
        self.sqrt_dims = tf.size(self.d) + tf.shape(W)[1]

    def get(self):
        return tf.diag(self.d) + tf.matmul(self.W, tf.transpose(self.W))

    def logdet(self):
        part1 = tf.reduce_sum(tf.log(self.d))
        I = eye(tf.shape(self.W)[1])
        M = I + tf.matmul(tf.transpose(self.W) / self.d, self.W)
        part2 = 2*tf.reduce_sum(tf.log(tf.diag_part(tf.cholesky(M))))
        return part1 + part2

    def matmul(self, B):
        WTB = tf.matmul(tf.transpose(self.W), B)
        WWTB = tf.matmul(self.W, WTB)
        DB = tf.reshape(self.d, [-1, 1]) * B
        return DB + WWTB

    def get_diag(self):
        return self.d + tf.reduce_sum(tf.square(self.W), 1)

    def solve(self, B):
        d_col = tf.expand_dims(self.d, 1)
        DiB = B / d_col
        DiW = self.W / d_col
        WTDiB = tf.matmul(tf.transpose(DiW), B)
        M = eye(tf.shape(self.W)[1]) + tf.matmul(tf.transpose(DiW), self.W)
        L = tf.cholesky(M)
        tmp1 = tf.matrix_triangular_solve(L, WTDiB, lower=True)
        tmp2 = tf.matrix_triangular_solve(tf.transpose(L), tmp1, lower=False)
        return DiB - tf.matmul(DiW, tmp2)

    def trace_KiX(self, X):
        """
        X is a square matrix of the same size as this one.
        if self is K, compute tr(K^{-1} X)
        """
        d_col = tf.expand_dims(self.d, 1)
        R = self.W / d_col
        RTX = tf.matmul(tf.transpose(R), X)
        RTXR = tf.matmul(RTX, R)
        M = eye(tf.shape(self.W)[1]) + tf.matmul(tf.transpose(R), self.W)
        Mi = tf.matrix_inverse(M)
        return tf.reduce_sum(tf.diag_part(X) * 1./self.d) - tf.reduce_sum(RTXR * Mi)

    def inv_diag(self):
        d_col = tf.expand_dims(self.d, 1)
        WTDi = tf.transpose(self.W / d_col)
        M = eye(tf.shape(self.W)[1]) + tf.matmul(WTDi, self.W)
        L = tf.cholesky(M)
        tmp1 = tf.matrix_triangular_solve(L, WTDi, lower=True)
        return 1./self.d - tf.reduce_sum(tf.square(tmp1), 0)

    def matmul_sqrt(self, B):
        """
        There's a non-square sqrt of this matrix given by
          [ D^{1/2}]
          [   W^T  ]

        This method right-multiplies the sqrt by the matrix B
        """

        DB = tf.expand_dims(tf.sqrt(self.d), 1) * B
        VTB = tf.matmul(tf.transpose(self.W), B)
        return tf.concat(0, [DB, VTB])

    def matmul_sqrt_transpose(self, B):
        """
        There's a non-square sqrt of this matrix given by
          [ D^{1/2}]
          [   W^T  ]

        This method right-multiplies the transposed-sqrt by the matrix B
        """
        B1 = tf.slice(B, tf.zeros((2,), tf.int32), tf.pack([tf.size(self.d), -1]))
        B2 = tf.slice(B, tf.pack([tf.size(self.d), 0]), -tf.ones((2,), tf.int32))
        return tf.expand_dims(tf.sqrt(self.d), 1) * B1 + tf.matmul(self.W, B2)


class Rank1Mat:
    def __init__(self, d, v):
        """
        A matrix of the form

            diag(d) + v v^T

        """
        self.d = d
        self.v = v
        self.shape = (tf.size(self.d), tf.size(self.d))
        self.sqrt_dims = tf.size(d) + 1

    def get(self):
        V = tf.expand_dims(self.v, 1)
        return tf.diag(self.d) + tf.matmul(V, tf.transpose(V))

    def logdet(self):
        return tf.reduce_sum(tf.log(self.d)) +\
            tf.log(1. + tf.reduce_sum(tf.square(self.v) / self.d))

    def matmul(self, B):
        V = tf.expand_dims(self.v, 1)
        return tf.expand_dims(self.d, 1) * B +\
            tf.matmul(V, tf.matmul(tf.transpose(V), B))

    def solve(self, B):
        div = self.v / self.d
        c = 1. + tf.reduce_sum(div * self.v)
        div = tf.expand_dims(div, 1)
        return B / tf.expand_dims(self.d, 1) -\
            tf.matmul(div/c, tf.matmul(tf.transpose(div), B))

    def trace_KiX(self, X):
        """
        X is a square matrix of the same size as this one.
        if self is K, compute tr(K^{-1} X)
        """
        R = tf.expand_dims(self.v / self.d, 1)
        RTX = tf.matmul(tf.transpose(R), X)
        RTXR = tf.matmul(RTX, R)
        M = 1 + tf.reduce_sum(tf.square(self.v) / self.d)
        return tf.reduce_sum(tf.diag_part(X) / self.d) - RTXR / M

    def get_diag(self):
        return self.d + tf.square(self.v)

    def inv_diag(self):
        div = self.v / self.d
        c = 1. + tf.reduce_sum(div * self.v)
        return 1./self.d - tf.square(div) / c

    def matmul_sqrt(self, B):
        """
        There's a non-square sqrt of this matrix given by
          [ D^{1/2}]
          [   V^T  ]

        This method right-multiplies the sqrt by the matrix B
        """

        DB = tf.expand_dims(tf.sqrt(self.d), 1) * B
        VTB = tf.matmul(tf.expand_dims(self.v, 0), B)
        return tf.concat(0, [DB, VTB])

    def matmul_sqrt_transpose(self, B):
        """
        There's a non-square sqrt of this matrix given by
          [ D^{1/2}]
          [   W^T  ]

        This method right-multiplies the transposed-sqrt by the matrix B
        """
        B1 = tf.slice(B, tf.zeros((2,), tf.int32), tf.pack([tf.size(self.d), -1]))
        B2 = tf.slice(B, tf.pack([tf.size(self.d), 0]), -tf.ones((2,), tf.int32))
        return tf.expand_dims(tf.sqrt(self.d), 1) * B1 + tf.matmul(tf.expand_dims(self.v, 1), B2)


class DiagMat:
    def __init__(self, d):
        self.d = d
        self.shape = (tf.size(self.d), tf.size(self.d))
        self.sqrt_dims = tf.size(d)

    def get(self):
        return tf.diag(self.d)

    def logdet(self):
        return tf.reduce_sum(tf.log(self.d))

    def matmul(self, B):
        return tf.expand_dims(self.d, 1) * B

    def solve(self, B):
        return B / tf.expand_dims(self.d, 1)

    def trace_KiX(self, X):
        """
        X is a square matrix of the same size as this one.
        if self is K, compute tr(K^{-1} X)
        """
        return tf.reduce_sum(tf.diag_part(X) / self.d)

    def get_diag(self):
        return self.d

    def inv_diag(self):
        return 1. / self.d

    def matmul_sqrt(self, B):
        return tf.expand_dims(tf.sqrt(self.d), 1) * B

    def matmul_sqrt_transpose(self, B):
        return tf.expand_dims(tf.sqrt(self.d), 1) * B
