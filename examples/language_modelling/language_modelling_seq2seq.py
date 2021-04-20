import torch
import torch.nn as nn
import torch.utils.data as tud
from tqdm.notebook import tqdm
from pprint import pprint
import numpy as np
import re
    
class Seq2SeqLanguageModel(Seq2Seq)
    def tensor2text(self, X, separator = "", vocabulary = None, end = "<END>"):
        if vocabulary is None:
            vocabulary = self.out_vocabulary
        return [re.sub(end + ".*", end, separator.join([vocabulary[i] for i in l])) for l in X.tolist()]
    
    def text2tensor(self, strings):
        return nn.utils.rnn.pad_sequence([torch.tensor([self.in_vocabulary[c] for c in l]) 
                                          for l in strings], 
                                         batch_first = True) 
    
    def fit(self, 
            X, 
            Y, 
            epochs = 10, 
            batch_size = 100, 
            lr = 0.0001, 
            verbose = 1,
            save_path = None):
        optimizer = torch.optim.Adam(self.parameters(), 
                                     lr)
        criterion = nn.CrossEntropyLoss(ignore_index = 0)
        dataset = tud.TensorDataset(X, Y)
        data_loader = tud.DataLoader(dataset, 
                                     batch_size = batch_size, 
                                     shuffle = True)
        for e in tqdm(range(1, epochs + 1) if verbose > 0 else range(1, epochs + 1)):
            losses = []
            for x, y in tqdm(iter(data_loader)) if verbose > 1 else iter(data_loader):
                predictions = self.forward(x, y).transpose(1, 2)
                loss = criterion(predictions[:, :, :-1], y[:, 1:])
                optimizer.zero_grad()
                loss.backward()
                losses.append(loss.item())
                optimizer.step()
            print(f"Epoch: {e:>4}, Loss: {sum(losses) / len(losses):.4f}")
            if verbose > 2:
                self.eval()
                print("Y")
                pprint(self.tensor2text(Y[:5, 1:]))
                print("forward")
                pprint(self.tensor2text(self.forward(X[:5], Y[:5]).argmax(-1)[:, :-1]))
                print("greedy_search")
                greedy = self.greedy_search(X[:5], 10)
                pprint(self.tensor2text(greedy[0][:, 1:]))
                print("sample")
                pprint(self.tensor2text(self.sample(X[:5], 10)[:, 1:]))
                print("beam_search")
                beam = self.beam_search(X[:5], max_predictions = 10, candidates = 5, beam_width = 5)
                pprint(np.array([self.tensor2text(t) for t in beam[0][:, :, 1:]]).T.tolist())
                pprint(((100 * greedy[1]).round() / 100))
                pprint(((100 * beam[1]).T.round() / 100))
                print("-" * 50)  
                self.train()
        if save_path is not None:
            torch.save(self.state_dict(), save_path)    
    def generate(self, input_text, 
                 max_predictions = 10,
                 method = "greedy_search", 
                 temperature = 1,
                 candidates = 5, 
                 beam_width = 5):
        X = self.text2tensor(input_text).to(next(self.parameters()).device)
        if method == "greedy_search":
            Y = self.greedy_search(X, max_predictions = max_predictions)
        elif method == "sample":
            assert temperature is not None
            Y = self.sample(X, max_predictions = max_predictions, temperature = temperature)
        elif method == "beam_search":
            assert candidates is not None
            assert beam_width is not None
            Y, log_probabilities = self.beam_search(X, max_predictions = max_predictions, candidates = candidates,
                                                    beam_width = beam_width)
            Y = Y[:, 0, :]
        else:
            raise ValueError('Unknown decoding method')
        return self.tensor2text(torch.cat((X, Y[:, 1:]), axis = 1))
  

class Seq2SeqRNN(Seq2SeqLanguageModel):
    def __init__(self, 
                 in_vocabulary, 
                 out_vocabulary, 
                 encoder_hidden_units = 100, 
                 encoder_layers = 1,
                 decoder_hidden_units = 100,
                 decoder_layers = 1):
        super().__init__()
        self.encoder = nn.LSTM(input_size = len(in_vocabulary), 
                               hidden_size = encoder_hidden_units, 
                               num_layers = encoder_layers)
        self.decoder = nn.LSTM(input_size = encoder_hidden_units + len(out_vocabulary), 
                               hidden_size = decoder_hidden_units, 
                               num_layers = decoder_layers)
        self.output_layer = nn.Linear(decoder_hidden_units, len(out_vocabulary))
        self.in_vocabulary = in_vocabulary
        self.out_vocabulary = out_vocabulary
        print(f"Net parameters: {sum([t.numel() for t in self.parameters()]):,}")
    
    def forward(self, X, Y):
        X = nn.functional.one_hot(X.T, len(self.in_vocabulary)).float()
        encoder, (encoder_last_hidden, encoder_last_memory) = self.encoder(X)
        encoder_last_hidden = encoder_last_hidden.repeat((Y.shape[1], 1, 1))
        Y = nn.functional.one_hot(Y.T, len(self.out_vocabulary)).float()
        Y = torch.cat((encoder_last_hidden, Y), axis = -1)
        decoder, (decoder_last_hidden, decoder_last_memory) = self.decoder(Y)
        output = self.output_layer(decoder).transpose(0, 1)
        return output

    
class Transformer(Seq2Seq):    
    def __init__(self, 
                 in_vocabulary, 
                 out_vocabulary, 
                 embedding_dimension = 100,
                 encoder_layers = 1,
                 decoder_layers = 1,
                 attention_heads = 2):
        super().__init__()
        self.in_embeddings = nn.Embedding(len(in_vocabulary), embedding_dimension)
        self.out_embeddings = nn.Embedding(len(out_vocabulary), embedding_dimension)
        self.positional_embeddings = nn.Embedding(350, embedding_dimension)
        self.transformer = nn.Transformer(d_model = embedding_dimension, 
                                          nhead = attention_heads, 
                                          num_encoder_layers = encoder_layers, 
                                          num_decoder_layers = decoder_layers)
        self.output_layer = nn.Linear(embedding_dimension, len(out_vocabulary))
        self.in_vocabulary = in_vocabulary
        self.out_vocabulary = out_vocabulary
        print(f"Net parameters: {sum([t.numel() for t in self.parameters()]):,}")
    
    def forward(self, X, Y):
        X = self.in_embeddings(X)
        X_positional = torch.arange(X.shape[1], device = next(self.parameters()).device).repeat((X.shape[0], 1))
        X_positional = self.positional_embeddings(X_positional)
        X = (X + X_positional).transpose(0, 1)
        Y = self.out_embeddings(Y)
        Y_positional = torch.arange(Y.shape[1], device = next(self.parameters()).device).repeat((Y.shape[0], 1))
        Y_positional = self.positional_embeddings(Y_positional)
        mask = self.transformer.generate_square_subsequent_mask(Y.shape[1]).to(next(self.parameters()).device)
        transformer = self.transformer(src = X, 
                                       tgt = (Y + Y_positional).transpose(0, 1), 
                                       tgt_mask = mask)
        output = self.output_layer(transformer.transpose(0, 1))
        return output