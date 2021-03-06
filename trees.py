'''
Tools to generate various types of synthetic data.
'''
import os
import numpy as np
import numpy.ma as ma
import random
from copy import deepcopy
from itertools import product
from graphviz import Digraph
from utils import *

class DecisionNode(object):
    def __init__(self, node_id, feature, children, weights):
        self.node_id = node_id
        self.feature = feature
        self.children = children
        self.weights = weights

    def classify(self, instance):
        '''
        Get the true classification probabilities for this instance,
        if all information is known.
        '''
        return self.children[instance.data[feature]].classify(instance)

    def predict(self, instance):
        '''
        Predicted the classification probabilities for this instance,
        where some features may be missing.
        '''
        if instance[self.feature] is ma.masked:
            # If we do not have this feature, marginalize it out
            return np.sum([w * c.predict(instance) for w,c in zip(self.weights, self.children)], axis=0)
        return self.children[instance.data[self.feature]].predict(instance)

    def feature_probs(self, instance, features, values, num_values_per_feature):
        '''
        Calculate the joint probability of the feature values given the
        instance.
        '''
        if self.feature in features:
            # Get the index of the feature value
            i = features.index(self.feature)
            fval = values[i]

            # Remove this feature from the lists
            features = features[0:i] + features[i+1:]
            values = values[0:i] + values[i+1:]

            # Weight the result by the likelihood of getting this feature value
            return self.weights[fval] * self.children[fval].feature_probs(instance, features, values, num_values_per_feature)
        
        # If this isn't one of the features, check if this feature is missing in the instance
        if instance[self.feature] is ma.masked:
            # If it is missing, consider all possible paths
            return np.sum([w * c.feature_probs(instance, features, values, num_values_per_feature) for w,c in zip(self.weights, self.children)])

        # If this feature is a conditional parameter, find that node and recurse on it
        return self.children[instance[self.feature]].feature_probs(instance, features, values, num_values_per_feature)

    def marginal(self, feature, num_values_per_feature):
        '''Calculate the marginal probability of each value for this feature'''
        if self.feature == feature:
            # If we are splitting on this feature, just return the splitting probs
            return weights
        result = np.zeros(num_values_per_feature)
        for child,weight in zip(self.children, self.weights):
            result += weight * child.marginal(feature, num_values_per_feature)

    def sample(self, instance):
        '''
        Build a new instance by sampling features.
        '''
        instance[self.feature] = weighted_sample(self.weights)
        self.children[instance.data[self.feature]].sample(instance)

    def graphviz_str(self):
        '''Generate a graphviz string description of the node.'''
        child_strs = [child.graphviz_str() for child in self.children]
        child_nodes = ''.join([nodes for nodes,edges in child_strs])
        child_edges = ''.join([edges for nodes,edges in child_strs])
        nodes = '{0}[label="f{1}"];'.format(self.node_id, self.feature)
        edges = ';'.join(['{0}->{1}[label="{2:.2f}"]'.format(self.node_id, self.children[i].node_id, self.weights[i]) for i in xrange(len(self.children))])
        return (nodes + child_nodes, edges + child_edges)

    def render(self, dot):
        '''Render the node graphically using the graphviz dot object.'''
        for child in self.children:
            child.render(dot)
        dot.node(str(self.node_id), 'f{0}'.format(self.feature))
        for weight,child in zip(self.weights,self.children):
            dot.edge(str(self.node_id), str(child.node_id), label='{0:.2f}'.format(weight))

class LeafNode(object):
    def __init__(self, node_id, probs):
        self.node_id = node_id
        self.probs = probs

    def classify(self, instance):
        return self.probs

    def predict(self, instance):
        return self.probs

    def feature_probs(self, instance, features, values, num_values_per_feature):
        # If we reached a leaf node, any remaining features are considered to be
        # uniformly distributed.
        return (1. / num_values_per_feature) ** len(features)

    def marginal(self, feature, num_values_per_feature):
        return np.ones(num_values_per_feature) / float(num_values_per_feature)

    def sample(self, instance):
        instance[-1] = weighted_sample(self.probs)

    def graphviz_str(self):
        nodes = '{0}[label="{1}"];'.format(self.node_id, pretty_str(self.probs))
        edges = ''
        return (nodes, edges)

    def render(self, dot):
        dot.node(str(self.node_id), pretty_str(self.probs))

class RootNode(object):
    def __init__(self, node_id, child):
        self.node_id = node_id
        self.children = [child]

    def classify(self, instance):
        return self.children[0].classify(instance)

    def predict(self, instance):
        return self.children[0].predict(instance)

    def feature_probs(self, instance, features, values, num_values_per_feature):
        return self.children[0].feature_probs(instance, features, values, num_values_per_feature)

    def marginal(self, feature, num_values_per_feature):
        return self.children[0].marginal(feature, num_values_per_feature)

    def sample(self, instance):
        return self.children[0].sample(instance)

    def graphviz_str(self):
        nodes, edges = self.children[0].graphviz_str()
        return nodes + edges

    def render(self, dot):
        return self.children[0].render(dot)

class GenerativeTree(object):
    '''
    A generative model for synthetic data.
    TODO: Add path coloring for a given instance
    '''
    def __init__(self, num_features, num_values_per_feature, num_classes, max_nodes, feature_bias=None, class_bias=None):
        assert(max_nodes > 0)
        self.num_features = num_features
        self.num_values_per_feature = num_values_per_feature
        self.num_classes = num_classes
        self.max_nodes = max_nodes
        self.feature_bias = np.ones(num_features) if feature_bias is None else feature_bias
        self.class_bias = np.ones(num_classes) if class_bias is None else class_bias
        self.marginals = [None for _ in xrange(num_features)]
        self.root = None
        self.build()

    def build(self):
        self.root = RootNode(0, self.create_leaf_node(1))
        next_id = 2
        for i in xrange(self.max_nodes - 1):
            features = range(self.num_features)
            next_id = self.try_to_add_node(self.root, features, next_id)

    def create_leaf_node(self, node_id):
        '''Create a random leaf node'''
        class_weights = np.random.dirichlet(self.class_bias)
        return LeafNode(node_id, class_weights)

    def try_to_add_node(self, node, features, next_id):
        '''
        Try to add a node to the tree by splitting on one of the available
        features.
        '''
        # If there are no remaining features we can add, we failed to add a node
        if len(features) == 0:
            return next_id

        # Pick one of the children nodes
        child_idx = random.choice(np.arange(len(node.children)))
        child = node.children[child_idx]

        # If we reached the end, we can add a node
        if type(child) is LeafNode:
            # Choose one of the remaining features and build the new node parameters
            idx = weighted_sample(self.feature_bias[features])
            feature = features[idx]
            children = [self.create_leaf_node(next_id + i) for i in xrange(self.num_values_per_feature)]
            weights = np.random.random(size=self.num_values_per_feature)
            weights /= weights.sum()

            # Add the new decision node
            node.children[child_idx] = DecisionNode(child.node_id, feature, children, weights)

            # We succeeded, so return the next node id
            return children[-1].node_id + 1

        # Otherwise we're at an internal node that has decision children.
        # Remove the child node's feature from the list of available features to split on
        features.remove(child.feature)

        # Recurse to a leaf node
        return self.try_to_add_node(child, features, next_id)

    def sample(self, count):
        '''Draw random samples from the tree.'''
        results = []
        for iteration in xrange(count):
            # Set all values to be random and known initially
            instance = ma.masked_array([random.choice(np.arange(self.num_values_per_feature)) for _ in xrange(self.num_features+1)],
                                        mask=np.zeros(self.num_features+1, dtype=int))

            # Sample our decision tree to add structure to the data.
            self.root.sample(instance)

            # Add the instance to the results
            results.append(instance)

        return ma.masked_array(results)

    def predict(self, instance):
        '''Calculate the distribution of class membership likelihood for the instance.'''
        return self.root.predict(instance)

    def conditional_probs(self, instance, features, values):
        '''Calculate the joint probability of the feature values given the instance.'''
        return self.root.feature_probs(instance, features, values, self.num_values_per_feature)

    def marginal(self, feature):
        '''Calculate the marginal probability distribution for the feature'''
        if self.marginals[feature] is None:
            # Calculate marginals in a lazy fashion for efficiency
            self.marginals[feature] = self.root.marginal(feature, self.num_values_per_feature)
        return self.marginals[feature]

    def graphviz_str(self):
        '''Generate a graphviz string of the tree.'''
        return self.root.graphviz_str()

    def render(self, filename):
        '''Create a PDF image of the tree.'''
        dot = Digraph()
        self.root.render(dot)
        dot.render(filename)
        os.remove(filename)
        os.rename(filename + '.pdf', filename)

class FeatureNode(object):
    def __init__(self, node_id, feature, children):
        self.node_id = node_id
        self.feature = feature
        self.children = children

    def render(self, dot):
        '''Render the node graphically using the graphviz dot object.'''
        for child in self.children:
            child.render(dot)
        dot.node(str(self.node_id), 'f{0}'.format(self.feature))
        for child in self.children:
            dot.edge(str(self.node_id), str(child.node_id))

class ValueNode(object):
    def __init__(self, node_id, features, children, values, weights):
        self.node_id = node_id
        self.features = features
        self.children = children
        self.values = values
        self.weights = weights

    def render(self, dot):
        '''Render the node graphically using the graphviz dot object.'''
        for child in self.children:
            child.render(dot)
        dot.node(str(self.node_id), '', style='filled')
        for i,child in enumerate(self.children):
            label = '\n'.join(['f{0}={1}'.format(f,v) for f,v in zip(self.features, self.values[i])]) + '\np={0:.2f}'.format(self.weights[i])
            dot.edge(str(self.node_id), str(child.node_id), label=label)

class StepRootNode(object):
    def __init__(self, node_id, children, step, prediction):
        self.node_id = node_id
        self.children = children
        self.step = step
        self.prediction = prediction

    def render(self, dot):
        '''Render the node graphically using the graphviz dot object.'''
        for child in self.children:
            child.render(dot)
        dot.node(str(self.node_id), label='Step {0}\n{1}'.format(self.step, pretty_str(self.prediction)))
        for child in self.children:
            dot.edge(str(self.node_id), str(child.node_id))

class FeatureAcquisitionTree(object):
    def __init__(self, instance, model, feature_model, feature_costs, budgets, optional_features, num_values_per_feature, num_classes, target_feature=None):
        self.instance = instance
        self.model = model
        self.feature_model = feature_model
        self.feature_costs = feature_costs
        self.budgets = budgets
        self.target_feature = target_feature
        self.optional_features = optional_features
        self.num_values_per_feature = num_values_per_feature
        self.num_classes = num_classes
        self.root = None
        self.num_nodes = None
        self.value = None
        self.gain = None
        self.build()

    def build(self):
        self.root = StepRootNode(0, [], 0, self.model.predict(self.instance))
        if self.target_feature is None:
            node = self.root
            remaining = self.budgets[0]
            purchased = []
            next_id = 1
        else:
            node = FeatureNode(1, self.target_feature, [])
            self.root.children.append(node)
            remaining = self.budgets[0] - self.feature_costs[self.target_feature]
            purchased = [self.target_feature]
            next_id = 2
        
        self.num_nodes, self.value = self.build_helper(node, self.optional_features, 0, remaining, purchased, self.instance, next_id)
        self.gain = self.value - max(self.root.prediction)
        #self.gain = -np.sum(self.root.prediction * np.log(self.root.prediction)) - self.value # measure information gain

    def build_helper(self, node, available, step, remaining, purchased, instance, next_id):
        can_afford_at_least_one_feature = False
        max_child_value = 0
        # Add each feature that is within our budget
        for i,feature in enumerate(available):
            child_remaining = remaining - self.feature_costs[feature]
            
            # If we can't afford it, skip this feature this step
            if child_remaining < 0:
                continue

            can_afford_at_least_one_feature = True

            # Create the child node
            child = FeatureNode(next_id, feature, [])
            
            # Recursively build the subtree with this feature acquired
            next_id, child_value = self.build_helper(child, available[0:i] + available[i+1:],
                                        step, child_remaining,
                                        purchased + [feature], instance, next_id + 1)

            # Add the child to its parent
            node.children.append(child)

            if child_value > max_child_value:
                max_child_value = child_value

        # If we were able to afford at least one feature, then we don't need a partition node here.
        if can_afford_at_least_one_feature:
            return (next_id, max_child_value)

        # Make this the partition node
        step += 1
        
        # Look at all combinations of results from the last step
        grandchildren_values = [x for x in product(xrange(self.num_values_per_feature), repeat=len(purchased))]

        child = ValueNode(next_id, purchased, [], grandchildren_values, [])
        next_id += 1

        # Consider every possible outcome of our feature acquisitions
        child_value = 0
        temp_data = instance.data[purchased]
        for vals in grandchildren_values:
            # Get the probability of this outcome actually occurring
            weight = self.feature_model.conditional_probs(instance, purchased, vals)
            child.weights.append(weight)

            # Set the feature values to this possibility
            instance[purchased] = vals

            # Get the prediction at this point
            prediction = self.model.predict(instance)

            # If we there is no next step, return the final prediction
            if step == len(self.budgets) or len(available) == 0:
                child.children.append(LeafNode(next_id, prediction))
                next_id += 1
                child_value += weight * np.max(prediction)
                #child_value += weight * -np.sum(prediction * np.log(prediction)) # Use information gain

            # Otherwise, start the whole process over again for each child node
            else:
                grandchild = StepRootNode(next_id, [], step, prediction)
                next_id, grandchild_value = self.build_helper(grandchild, available, step, self.budgets[step], [], instance, next_id + 1)
                child.children.append(grandchild)
                child_value += weight * grandchild_value

        # Undo the temporary changes to the instance
        instance.data[purchased] = temp_data
        instance.mask[purchased] = 1

        # Add the child to its parent
        node.children.append(child)

        return (next_id, child_value)

    def render(self, filename):
        '''Create a PDF image of the tree.'''
        dot = Digraph()
        self.root.render(dot)
        dot.render(filename)
        os.remove(filename)
        os.rename(filename + '.pdf', filename)







