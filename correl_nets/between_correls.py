__author__ = 'shafferm'

from biom import load_table
from scipy.stats import spearmanr, pearsonr
import general
import os
import networkx as nx


def between_correls_from_tables(table1, table2, correl_method=spearmanr, p_adjust=general.bh_adjust):
    otus1 = table1.ids(axis="observation")
    otus2 = table2.ids(axis="observation")

    correls = list()

    for otu1 in otus1:
        row1 = table1.data(otu1, axis="observation")
        for otu2 in otus2:
            row2 = table2.data(otu2, axis="observation")
            corr = correl_method(row1, row2)
            correls.append([otu1, otu2, corr[1], corr[2]])

    p_adjusted = p_adjust([i[3] for i in correls])
    for i in xrange(len(correls)):
            correls[i].append(p_adjusted[i])

    return correls, ['feature1', 'feature2', 'r', 'p', 'p_adj']


def between_correls(args):

    # correlation and p-value adjustment methods
    correl_methods = {'spearman': spearmanr, 'pearson': pearsonr}
    p_methods = {'bh': general.bh_adjust, 'bon': general.bonferroni_adjust}
    correl_method = correl_methods[args.correl_method]
    if args.p_adjust is not None:
        p_adjust = p_methods[args.p_adjust]
    else:
        p_adjust = None

    # load tables
    table1 = load_table(args.table1)
    table2 = load_table(args.table2)

    # make new output directory and change to it
    if args.output is not None:
        os.makedirs(args.output)
        os.chdir(args.output)

    # filter tables
    table1 = general.filter_table(table1)
    metadata = general.get_metadata_from_table(table1)
    table2 = general.filter_table(table2)
    metadata.update(general.get_metadata_from_table(table2))

    # make correlations
    correls, correl_header = between_correls_from_tables(table1, table2, correl_method, p_adjust)
    general.print_delimited('correls.txt', correls, correl_header)

    # make network
    net = general.correls_to_net(correls, metadata=metadata, min_p=args.min_p)
    nx.write_gml(net, 'crossnet.gml')

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-1", "--table1", help="table to be correlated")
    parser.add_argument("-2", "--table2", help="second table to be correlated")
    parser.add_argument("-o", "--output", help="output file location")
    parser.add_argument("-m", "--correl_method", help="correlation method", default="spearman")
    parser.add_argument("-a", "--p_adjust", help="p-value adjustment", default="bh")
    parser.add_argument("-s", "--min_sample", help="minimum number of samples present in", type=int)
    parser.add_argument("--min_p", help="minimum p-value to determine edges", default=.05, type=float)

    between_correls(parser.parse_args())