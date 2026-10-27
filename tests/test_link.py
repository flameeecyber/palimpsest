import numpy as np

from palimpsest.link import cluster_vectors


def test_cluster_vectors_groups_similar_rows():
    vectors = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.99, 0.01, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    groups = cluster_vectors(vectors, threshold=0.9)
    assert sorted(len(g) for g in groups) == [1, 2]


def test_cluster_vectors_keeps_everything():
    vectors = np.eye(4, dtype=np.float32)
    groups = cluster_vectors(vectors, threshold=0.5)
    assert sum(len(g) for g in groups) == 4
