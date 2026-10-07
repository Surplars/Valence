obj-m += valence_gmac.o
obj-m += valence_aia.o
obj-$(CONFIG_VALENCE_SOC) += valence_soc.o
ifeq ($(CONFIG_VALENCE_CMU),y)
obj-m += valence_cmu.o
endif
ifeq ($(CONFIG_VALENCE_DMA),y)
obj-m += valence_dma.o
endif
ccflags-y += -I$(srctree)/drivers/dma
