import matplotlib
matplotlib.use('agg')
import os,glob
import pandas as pd
import argparse
from natsort import natsorted
from multiprocessing import Pool
import matplotlib.pyplot as plt
plt.style.use('ggplot')



parser = argparse.ArgumentParser(description='Calibrate P-site distance by plotting the coverge around TSS and TSE')
parser.add_argument('-b','--bam_path',action='store',dest='bam_path',help='bam path for storing all results')
parser.add_argument('-g','--gff_path',action='store',dest='gff_path',help='path to all files generated by p01_prepare_annotation.py')
parser.add_argument('-s','--min_len',action='store',dest='min_len',type=int,help='minimum mapping to conisder to get position',default=20)
parser.add_argument('-e','--max_len',action='store',dest='max_len',type=int,help='maximum mapping to conisder to get position',default=37)
parser.add_argument('-t','--thread',action='store',dest='thread',type=int,help='number of thread',default=1)
args = parser.parse_args()

bam_path = args.bam_path
if bam_path.endswith('/'): bam_path = bam_path[:-1]
path = os.path.dirname(bam_path)
db_path = args.gff_path
start = args.min_len
end   = args.max_len
lens  = range(start,end + 1)
thread  = args.thread

def get_pos_dic(bed):
    '''this function builds dictioanry for protein or rna {id:[strand, (s1,e1),(s2,e2)]}'''
    dic = {}
    with open(bed) as f:
        for line in f:
            if line.startswith('Chr'): continue
            item = line.strip().split('\t')
            if item[4] in dic:
                dic[item[4]].append((item[1],item[2]))
            else:
                dic[item[4]] = [item[-1],(item[1],item[2])]
    return dic

def get_pos(dic,access):
    if access not in dic:
        pos = []
    else:
        strd = dic[access][0]
        pos = []
        for p in dic[access][1:]:
            pos.extend(range(int(p[0])+1,int(p[1])+1))
        if strd == '-':
            pos = pos[::-1]
    return pos


def get_pr_window_pos(pr,utr_df,exn_pos_dic,cds_pos_dic,tsse,up,dn):
    '''get window position upstream and downstream of TSS or TSE'''
    chrom    = utr_df.loc[pr,'Chrom']
    tr       = utr_df.loc[pr,'TrAccess']
    gid      = utr_df.loc[pr,'GeneID']
    utr5_len = int(utr_df.loc[pr,'utr5_len'])
    utr3_len = int(utr_df.loc[pr,'utr3_len'])
    strd     = utr_df.loc[pr,'strand']
    # get rna position
    tr_pos = get_pos(exn_pos_dic,tr)
    if tr_pos == []:
        tr_pos = get_pos(cds_pos_dic,pr)
    def get_window_pos(tr_pos,utr_len,utr_type,up,dn):
        '''given a position of a rna, it extracts the up or down stream sequence of TSS or TSE'''
        # get rna position
        tr_start = tr_pos[0];tr_end = tr_pos[-1]
        # get window position
        if tr_pos[0] < tr_pos[1]:
            new_pos = range(tr_start-up,tr_start) + tr_pos + range(tr_end+1,tr_end+dn+1)
        else:
            new_pos = range(tr_start+up,tr_start,-1)+tr_pos+ range(tr_end-1,tr_end-dn-1,-1)
        if utr_type == '5':
            window = new_pos[utr_len:utr_len+up+dn+1]
        elif utr_type == '3':
            window = new_pos[-utr_len-up-dn-1:-utr_len-1] + [new_pos[-utr_len-1]]
        return window

    # get window position around TSS or TSE position of each protein
    if tsse == 'tss':
        window = get_window_pos(tr_pos,utr5_len,'5',up,dn)
    else:
        window = get_window_pos(tr_pos,utr3_len,'3',up,dn)
    return chrom,window


def cov5_3_dic(covFile,m_len):
    '''prepare two dictionaries for mapping of 5end and 3end of the reads.
    format {chr:{pos+/-:count}}'''
    cov_5dic = {}
    cov_3dic = {}
    with open(covFile) as cov:
        for line in cov:
            item = line.strip().split('\t')
            if int(item[-1]) != m_len: continue
            count = int(item[0])
            chrom = item[1]
            end5  = item[2]
            end3  = item[3]
            strd  = item[4]
            if chrom in cov_5dic:
                cov_5dic[chrom][end5+strd] = count
                cov_3dic[chrom][end3+strd] = count
            else:
                cov_5dic[chrom] = {}
                cov_3dic[chrom] = {}
    return cov_5dic,cov_3dic


def get_pos_cov(dic5,dic3,chrom,pos,end):
    if pos[0]<pos[1]:
        strd = '+'
    else:
        strd = '-'
    pos_cov = []
    for p in pos:
        try:
            if end == '5' and strd == '+':
                pos_cov.append(dic5[chrom][str(p)+strd])
            elif end == '5' and strd == '-':
                pos_cov.append(dic3[chrom][str(p)+strd])
            elif end == '3' and strd == '+':
                pos_cov.append(dic3[chrom][str(p)+strd])
            elif end == '3' and strd == '-':
                pos_cov.append(dic5[chrom][str(p)+strd])
        except:
            pos_cov.append(0)
    return pos_cov


def get_tsse_cov(p_site_path,exnFile,cdsFile,covFile,m_len,utrFile,up,dn,end,tsse):
    '''
    * end: 3 or 5
    '''
    window_path = p_site_path + '/' + os.path.basename(covFile)[:-4]
    if not os.path.exists(window_path): os.mkdir(window_path)
    outFile = window_path + '/' + tsse + end + '_' + str(m_len) + '.txt'
    # pos dic
    exn_pos_dic = get_pos_dic(exnFile)
    cds_pos_dic = get_pos_dic(cdsFile)
    # cover data
    dic5,dic3 = cov5_3_dic(covFile,m_len)
    # utr_df
    utr_df = pd.read_csv(utrFile,sep='\t',header=0)
    utr_df.index = utr_df['PrAccess']
    prs = list(set(utr_df['PrAccess']))
    with open(outFile,'w') as f:
        for pr in prs:#['heavychain_prid']:
            chrom,window = get_pr_window_pos(pr,utr_df,exn_pos_dic,cds_pos_dic,tsse,up,dn)
            # get coverage at window position
            win_cov = get_pos_cov(dic5,dic3,chrom,window,end)
            win_cov = [str(p) for p in win_cov]
            f.write('\t'.join([pr]+win_cov)+'\n')

def wrap_get_tsse_cov(p_site_path,exnFile,cdsFile,covFile,map_lens,utrFile,up,dn,end,tsse,thread):
    p = Pool(processes=thread)
    for l in map_lens:
        p.apply_async(get_tsse_cov,args=(p_site_path,exnFile,cdsFile,covFile,l,utrFile,up,dn,end,tsse))
    p.close()
    p.join()


def plt_figs(folder,tsse,end,up,dn):
    files = natsorted(glob.glob(folder+'/' + tsse + end + '*.txt'))
    # For each length, overlay counts in the window across all genes
    cov_df = pd.DataFrame()
    for f in files:
        df = pd.read_csv(f,sep='\t',header=None,index_col=0)
        sum_df = df.sum()
        sum_df.columns = [os.path.basename(f)[:-4]]
        cov_df[os.path.basename(f)[:-4]] = sum_df   
    # plot
    x = range(-up,dn+1)
    n = 9
    groups = [range(len(files))[l:l+n] for l in range(0,len(files),n)]
    for g in range(len(groups)):
        num = len(groups[g])
        f,ax= plt.subplots(num,sharex=True,figsize=(9,10))
        for i in range(n):
            index = i + g*n 
            try:
                name = cov_df.columns[index]
            except:
                continue
            ax[i].bar(x,cov_df.iloc[:,index],label=name,align='center')
            handles, labels = ax[i].get_legend_handles_labels()
            ax[i].legend(handles[::-1],labels[::-1])
        f.suptitle('coverage around ' +  tsse.upper(),fontsize=16)
        f.subplots_adjust(top=0.96)
        plt.savefig('{f}/{t}{e}_batch{b}.png'.format(f=folder,t=tsse,e=end,b=g))
    sum_all = cov_df.sum(axis=1)
    f,ax = plt.subplots(figsize=(8,4))
    ax.bar(x,sum_all,align='center')
    ax.set_title('coverage around '+tsse)
    plt.savefig('{f}/{t}{e}.png'.format(f=folder,t=tsse,e=end)) 


def plot_align_len_distr(df,fig):
    filter_df = df[df['m_len'].values<50].groupby('m_len').sum()
    ax = filter_df.plot(figsize=(8,4))
    _ = ax.set_title('map length distribution')
    _ = ax.set_xticks(range(20,50))
    plt.savefig(fig)

# read in files and create pathways
cdsFile = db_path + '/01_pr_cds.bed'
exnFile = db_path + '/01_pr_rna.bed'
p_site_path =  path + '/03_Psite'
if not os.path.exists(p_site_path): os.mkdir(p_site_path)
# prepare {id:position} dictionary
long_utr_fn = db_path + '/04_long_utr_len.txt'
cds_pos_dic = get_pos_dic(cdsFile)
exn_pos_dic = get_pos_dic(exnFile)
print('dictionary preparation succeed')


# read coverage dataframe
cov_path = path + '/02_cov'
covFiles = natsorted(glob.glob(cov_path+'/*.txt'))
# get position around tss and tse
up = 50
dn = 50
end = '5'
p_site_path = path + '/03_Psite'
utrFile = db_path + '/04_long_utr_len.txt'
for covFile in covFiles:
    # get mapping length
    cov_df = pd.read_csv(covFile,sep='\t',header=None,usecols=[0,5],names=['count','m_len'])
    map_lens = sorted(list(set(cov_df['m_len'])))
    map_lens = sorted(list(set(map_lens).intersection(lens)))
    # get coverage around tss and tse
    wrap_get_tsse_cov(p_site_path,exnFile,cdsFile,covFile,map_lens,utrFile,up,dn,end,'tss',thread)
    wrap_get_tsse_cov(p_site_path,exnFile,cdsFile,covFile,map_lens,utrFile,up,dn,end,'tse',thread)
    print('coverage around tss/tse succeed for file ' + covFile)
    # plot length distribution
    folder = p_site_path + '/' + os.path.basename(covFile)[:-4]
    plot_align_len_distr(cov_df,folder+'/map_len_dist.png')
    # plot the coverage around tss and tse    
    plt_figs(folder,'tss',end,up,dn)
    plt_figs(folder,'tse',end,up,dn)
print('plot succeed')