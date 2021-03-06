from scipy.stats import spearmanr
import warnings
from functools import partial
import pandas as pd
from biom.table import Table
import subprocess
from itertools import combinations
import tempfile
from os import path
from glob import glob

from SCNIC.general import p_adjust


def df_to_correls(cor, col_label='r'):
    """takes a square correlation dataframe and turns it into a long form dataframe"""
    cor.index = [str(i) for i in cor.index]
    cor.columns = [str(i) for i in cor.columns]
    correls = pd.DataFrame(cor.stack().loc[list(combinations(cor.index, 2))], columns=[col_label])
    return correls


def calculate_correlations(table: Table, corr_method=spearmanr, p_adjustment_method: str = 'fdr_bh') -> pd.DataFrame:
    # TODO: multiprocess this
    index = list()
    data = list()
    for (val_i, id_i, _), (val_j, id_j, _) in table.iter_pairwise(axis='observation'):
        r, p = corr_method(val_i, val_j)
        index.append((id_i, id_j))
        data.append((r, p))
    correls = pd.DataFrame(data, index=index, columns=['r', 'p'])
    correls.index = pd.MultiIndex.from_tuples(correls.index)  # Turn tuple index into actual multiindex
    if p_adjustment_method is not None:
        correls['p_adjusted'] = p_adjust(correls.p, method=p_adjustment_method)
    return correls


def fastspar_correlation(table: Table, verbose: bool=False, nprocs=1) -> pd.DataFrame:
    # TODO: multiprocess support
    with tempfile.TemporaryDirectory(prefix='fastspar') as temp:
        table.to_dataframe().to_dense().to_csv(path.join(temp, 'otu_table.tsv'), sep='\t', index_label='#OTU ID')
        if verbose:
            stdout = None
        else:
            stdout = subprocess.DEVNULL
        subprocess.run(['fastspar', '-c',  path.join(temp, 'otu_table.tsv'), '-r',
                        path.join(temp, path.join(temp, 'correl_table.tsv')), '-a',
                        path.join(temp, 'covar_table.tsv'), '-t', str(nprocs)],  stdout=stdout)
        cor = pd.read_table(path.join(temp, 'correl_table.tsv'), index_col=0)
        return df_to_correls(cor)



def fastspar_correlation_permutation(table: Table, verbose: bool=False, nprocs=1, bootstraps=1000) -> pd.DataFrame:
    # TODO: multiprocess support
    with tempfile.TemporaryDirectory(prefix='fastspar') as temp:
        table.to_dataframe().to_dense().to_csv(path.join(temp, 'otu_table.tsv'), sep='\t', index_label='#OTU ID')
        if verbose:
            stdout = None
        else:
            stdout = subprocess.DEVNULL
        # generate correlation table, -r, to compare against bootstraps
        subprocess.run(['fastspar', '-c',  path.join(temp, 'otu_table.tsv'), '-r',
                        path.join(temp, path.join(temp, 'correl_table.tsv')), '-a',
                        path.join(temp, 'covar_table.tsv'), '-t', str(nprocs)], stdout=stdout)
        # generate bootstraps with prefix, boot
        #subprocess.run(['mkdir', path.join(temp, 'bootstraps')])
        subprocess.run(['fastspar_bootstrap', '-c',  path.join(temp, 'otu_table.tsv'), '-n',
                        str(bootstraps), '-p', path.join(temp, 'boot'),
                        '-t', str(nprocs)], stdout=stdout)
        # infer correlations for each bootstrap count using all available processes
        # TODO specify number of dedicated processes
        subprocess.run(['ls', temp], stdout=stdout)
        subprocess.run(['parallel', '-j', str(nprocs), 'fastspar', '-c', '{}', '-r',
                        path.join(temp, 'cor_{/}'), '-a', path.join(temp, 'cov_{/}'), '-i', str(5),
                        ':::'] + glob(path.join(temp, 'boot*')), stdout=stdout)
        # caluculate p_values for correlation table
        subprocess.run(['fastspar_exactpvalues', '-c', path.join(temp, 'otu_table.tsv'), '-r',
                         path.join(temp, 'correl_table.tsv'), '-p', path.join(temp, 'cor_boot'),
                         '-t', str(nprocs), '-n', str(bootstraps), '-o',
                         path.join(temp, 'pvalues.tsv')], stdout=stdout)

        cor = pd.read_table(path.join(temp, 'correl_table.tsv'), index_col=0)
        pvals = pd.read_table(path.join(temp, 'pvalues.tsv'), index_col=0)
        return pd.concat([df_to_correls(cor), df_to_correls(pvals, col_label='pvalue')], axis=1, join='inner')



def between_correls_from_tables(table1, table2, correl_method=spearmanr, nprocs=1):
    """Take two biom tables and correlation"""
    correls = list()

    if nprocs == 1:
        for data_i, otu_i, _ in table1.iter(axis="observation"):
            for data_j, otu_j, _ in table2.iter(axis="observation"):
                corr = correl_method(data_i, data_j)
                correls.append([otu_i, otu_j, corr[0], corr[1]])
    else:
        import multiprocessing
        if nprocs > multiprocessing.cpu_count():
            warnings.warn("nprocs greater than CPU count, using all avaliable CPUs")
            nprocs = multiprocessing.cpu_count()

        pool = multiprocessing.Pool(nprocs)
        for data_i, otu_i, _ in table1.iter(axis="observation"):
            datas_j = (data_j for data_j, _, _ in table2.iter(axis="observation"))
            corr = partial(correl_method, b=data_i)
            corrs = pool.map(corr, datas_j)
            correls += [(otu_i, table2.ids(axis="observation")[i], corrs[i][0], corrs[i][1])
                        for i in range(len(corrs))]
        pool.close()
        pool.join()

    correls = pd.DataFrame(correls, columns=['feature1', 'feature2', 'r', 'p'])
    return correls.set_index(['feature1', 'feature2'])  # this needs to be fixed, needs to return multiindex
